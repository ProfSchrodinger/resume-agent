import os
import json
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
import anthropic
import zipfile
import io
import tempfile
from datetime import datetime

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

RESUME_FILES = ["experience.tex", "projects.tex", "skills.tex", "activities.tex"]
READONLY_FILES = ["heading.tex", "education.tex", "custom-commands.tex", "resume.tex"]

def get_repo_path():
    return os.environ.get("RESUME_REPO_PATH", "")

def read_file(repo_path, filename):
    candidates = [
        Path(repo_path) / "src" / filename,
        Path(repo_path) / filename,
    ]
    for p in candidates:
        if p.exists():
            return p.read_text()
    return None

def read_projects_bank(repo_path):
    candidates = [
        Path(repo_path) / "src" / "projects-bank.tex",
        Path(repo_path) / "projects-bank.tex",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text()
    return read_file(repo_path, "projects.tex") or ""

def build_master_context(repo_path):
    ctx = {}
    for f in RESUME_FILES + READONLY_FILES:
        content = read_file(repo_path, f)
        if content:
            ctx[f] = content
    ctx["projects-bank.tex"] = read_projects_bank(repo_path)
    return ctx

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/check-config")
def check_config():
    repo_path = get_repo_path()
    api_key = ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    issues = []
    if not repo_path:
        issues.append("RESUME_REPO_PATH not set")
    elif not Path(repo_path).exists():
        issues.append(f"Repo path does not exist: {repo_path}")
    if not api_key:
        issues.append("ANTHROPIC_API_KEY not set")
    
    files_found = []
    if repo_path and Path(repo_path).exists():
        for f in RESUME_FILES:
            if read_file(repo_path, f):
                files_found.append(f)
    
    return jsonify({"ok": len(issues) == 0, "issues": issues, "files_found": files_found})

@app.route("/api/tailor", methods=["POST"])
def tailor():
    data = request.json
    jd = data.get("jd", "").strip()
    company = data.get("company", "Company").strip()
    role = data.get("role", "Role").strip()
    api_key = data.get("api_key", "").strip() or ANTHROPIC_API_KEY

    if not jd:
        return jsonify({"error": "Job description is required"}), 400
    if not api_key:
        return jsonify({"error": "Anthropic API key is required"}), 400

    repo_path = get_repo_path()
    if not repo_path:
        return jsonify({"error": "RESUME_REPO_PATH environment variable not set"}), 400

    ctx = build_master_context(repo_path)
    if not ctx:
        return jsonify({"error": "Could not read resume files from repo path"}), 400

    client = anthropic.Anthropic(api_key=api_key)

    files_block = "\n\n".join([f"=== {k} ===\n{v}" for k, v in ctx.items()])

    prompt = f"""You are an expert resume tailoring assistant. You will tailor a LaTeX resume for a specific job.

## RESUME FILES (master copies)
{files_block}

## TARGET JOB
Company: {company}
Role: {role}
Job Description:
{jd}

## YOUR TASK
Produce tailored versions of ONLY these three files: experience.tex, projects.tex, skills.tex

Rules:
1. EXPERIENCE.TEX:
   - For each job, select the BEST 3-5 bullet points that match the JD
   - Uncomment variants that better match the JD (e.g. AWS variant vs Azure variant)
   - Comment out weaker bullets with %
   - Rewrite active bullets to naturally include JD keywords where truthful
   - Keep ALL job entries (Brightstar, Uber Senior, Uber Intern) — never remove a job
   - Preserve all LaTeX formatting exactly

2. PROJECTS.TEX:
   - Choose the 2-3 BEST projects from projects-bank.tex that match this role
   - For chosen projects, pick the best bullet variant (uncomment it, comment others)
   - Comment out non-selected projects entirely with %
   - Preserve all LaTeX formatting and hyperlinks exactly

3. SKILLS.TEX:
   - Reorder items within each category to front-load the most JD-relevant skills
   - Do NOT add skills that aren't already there
   - Keep all four rows (Languages & Tools, Machine Learning, Libraries & Visualization, Soft Skills)

4. ONE PAGE CHECK:
   - Count approximate line usage. A standard resume fits ~52-55 lines of content.
   - If over budget, trim lower-priority bullets (comment them out).
   - Report estimated line count in your analysis.

## OUTPUT FORMAT
Return ONLY valid JSON in this exact structure, no markdown, no explanation outside JSON:
{{
  "analysis": {{
    "role_type": "...",
    "key_skills_matched": ["skill1", "skill2"],
    "projects_selected": ["project1", "project2"],
    "bullets_changed": 3,
    "estimated_lines": 52,
    "one_page_fit": true,
    "reasoning": "2-3 sentence summary of tailoring decisions"
  }},
  "files": {{
    "experience.tex": "...full file content...",
    "projects.tex": "...full file content...",
    "skills.tex": "...full file content..."
  }}
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        # Build diffs
        diffs = {}
        for fname in ["experience.tex", "projects.tex", "skills.tex"]:
            original = ctx.get(fname, "")
            tailored = result["files"].get(fname, "")
            diffs[fname] = build_diff(original, tailored)

        return jsonify({
            "analysis": result["analysis"],
            "files": result["files"],
            "diffs": diffs,
            "company": company,
            "role": role
        })

    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse AI response: {str(e)}", "raw": raw[:500]}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def build_diff(original, tailored):
    orig_lines = original.splitlines()
    tail_lines = tailored.splitlines()
    diff = []
    
    orig_set = set(orig_lines)
    tail_set = set(tail_lines)
    
    # Simple line-by-line diff
    max_len = max(len(orig_lines), len(tail_lines))
    o_idx, t_idx = 0, 0
    
    while o_idx < len(orig_lines) or t_idx < len(tail_lines):
        o_line = orig_lines[o_idx] if o_idx < len(orig_lines) else None
        t_line = tail_lines[t_idx] if t_idx < len(tail_lines) else None
        
        if o_line == t_line:
            diff.append({"type": "same", "line": o_line})
            o_idx += 1
            t_idx += 1
        elif o_line is not None and t_line is not None:
            # Check if one was commented/uncommented version of other
            o_stripped = o_line.lstrip("% ").strip()
            t_stripped = t_line.lstrip("% ").strip()
            if o_stripped == t_stripped:
                if o_line.strip().startswith("%") and not t_line.strip().startswith("%"):
                    diff.append({"type": "added", "line": t_line})
                    diff.append({"type": "removed", "line": o_line})
                else:
                    diff.append({"type": "removed", "line": o_line})
                    diff.append({"type": "added", "line": t_line})
                o_idx += 1
                t_idx += 1
            else:
                diff.append({"type": "removed", "line": o_line})
                diff.append({"type": "added", "line": t_line})
                o_idx += 1
                t_idx += 1
        elif o_line is not None:
            diff.append({"type": "removed", "line": o_line})
            o_idx += 1
        else:
            diff.append({"type": "added", "line": t_line})
            t_idx += 1

    return diff

@app.route("/api/save", methods=["POST"])
def save():
    data = request.json
    files = data.get("files", {})
    company = data.get("company", "company").strip().lower().replace(" ", "-")
    role = data.get("role", "role").strip().lower().replace(" ", "-")
    repo_path = get_repo_path()

    if not repo_path:
        return jsonify({"error": "RESUME_REPO_PATH not set"}), 400

    date_str = datetime.now().strftime("%Y%m%d")
    output_dir = Path(repo_path) / "tailored" / f"{company}_{role}_{date_str}"
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for fname, content in files.items():
        out_path = output_dir / fname
        out_path.write_text(content)
        saved.append(str(out_path))

    # Also write a manifest
    manifest = {
        "company": data.get("company"),
        "role": data.get("role"),
        "date": date_str,
        "analysis": data.get("analysis", {})
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Create zip for download
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Include tailored files
        for fname, content in files.items():
            zf.writestr(f"src/{fname}", content)
        # Include readonly files as-is
        for fname in READONLY_FILES:
            content = read_file(repo_path, fname)
            if content:
                if fname in ["heading.tex", "education.tex", "activities.tex"]:
                    zf.writestr(f"src/{fname}", content)
                else:
                    zf.writestr(fname, content)
        # Include manifest
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    
    zip_buffer.seek(0)
    zip_name = f"resume_{company}_{role}_{date_str}.zip"
    
    # Save zip to output dir too
    zip_path = output_dir / zip_name
    zip_path.write_bytes(zip_buffer.getvalue())

    return jsonify({
        "saved_to": str(output_dir),
        "zip_name": zip_name,
        "zip_path": str(zip_path),
        "files_saved": saved
    })

@app.route("/api/download-zip", methods=["POST"])
def download_zip():
    data = request.json
    zip_path = data.get("zip_path")
    zip_name = data.get("zip_name", "resume.zip")
    if not zip_path or not Path(zip_path).exists():
        return jsonify({"error": "Zip not found"}), 404
    return send_file(zip_path, as_attachment=True, download_name=zip_name)

@app.route("/api/history")
def history():
    repo_path = get_repo_path()
    if not repo_path:
        return jsonify([])
    tailored_dir = Path(repo_path) / "tailored"
    if not tailored_dir.exists():
        return jsonify([])
    entries = []
    for d in sorted(tailored_dir.iterdir(), reverse=True):
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            m["folder"] = d.name
            entries.append(m)
    return jsonify(entries)

if __name__ == "__main__":
    print("\n🚀 Resume Tailoring Agent")
    print("=" * 40)
    repo = get_repo_path()
    print(f"Repo path: {repo or '(not set — set RESUME_REPO_PATH)'}")
    api = ANTHROPIC_API_KEY
    print(f"API key:   {'set ✓' if api else '(not set — set ANTHROPIC_API_KEY or enter in UI)'}")
    print("=" * 40)
    print("Open: http://localhost:5000\n")
    app.run(debug=True, port=5000)
