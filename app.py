import os
import json
import re
import shutil
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file
import anthropic
import tempfile
from datetime import datetime

app = Flask(__name__)

@app.after_request
def add_no_cache(response):
    if request.path == '/':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response

PDFLATEX = "/Library/TeX/texbin/pdflatex"
JOB_APPS_DIR = Path.home() / "Downloads" / "ApplyDocumentsAgent"

RESUME_FILES = ["experience.tex", "projects.tex", "skills.tex", "activities.tex"]
READONLY_FILES = ["heading.tex", "education.tex", "custom-commands.tex", "resume.tex"]

def load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

load_env()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

def get_repo_path():
    raw = os.environ.get("RESUME_REPO_PATH", "")
    if not raw:
        return ""
    p = Path(raw)
    if not p.is_absolute():
        # resolve relative to app.py location
        p = (Path(__file__).parent / p).resolve()
    return str(p)

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
    for f in RESUME_FILES:
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
Produce tailored versions of ONLY experience.tex and projects.tex.
Also produce a scoring analysis BEFORE and AFTER tailoring.

---

## PART 1 — GENERAL RULES (apply to BOTH files)

1. BULLET LENGTH — STRICT RANGE:
   - Every \\resumeItem bullet must be between 210 and 245 characters (counting all text inside the braces).
   - Target 210-230 characters as the sweet spot — enough to pack in JD keywords without overflowing.
   - Before writing each bullet, count the characters. If it exceeds 245, cut words until it fits.
   - No bullet may fall outside the 210-245 character count range. No exceptions. Hold on this rule above all else.

2. LANGUAGE MIRRORING — PRIMARY GOAL:
   - Before writing anything, extract a vocabulary list from the JD: industry terms, action verbs, methodologies, buzzwords, and product names the company uses.
   - Every bullet in BOTH files must use 1-2 phrases directly lifted from the JD vocabulary list.
   - Use the company's exact words, not synonyms.
   - Mirror sentence structure: noun-heavy JD → noun-heavy bullets; verb-heavy JD → verb-heavy bullets.
   - Facts, tools, and metrics must stay truthful — only framing and vocabulary changes.

3. LATEX FORMATTING:
   - Preserve all LaTeX commands, bold tags, and special characters exactly.
   - Update \\textbf{{}} tags to bold newly inserted JD keywords.
   - Never break LaTeX syntax.

---

## PART 2 — EXPERIENCE.TEX RULES

1. KEEP ALL BULLET POINTS — do not add or remove any bullet. Every bullet must appear, either active or commented.
2. REWRITING:
   - Lead each bullet with a strong action verb matching the JD tone.
   - Swap generic terms for JD-specific equivalents where truthful.
   - Weave in 1-2 JD keywords naturally per bullet.
   - Never invent metrics or tools not in the original bullet.
3. SAMSUNG INTERN: uncomment only if the role is ML, software, or data engineering. Otherwise keep commented.
4. Do not change the order of jobs or bullets.

---

## PART 3 — PROJECTS.TEX RULES

1. ALWAYS include Boston 311 Dashboard & Chatbot with EXACTLY 2 bullet points.
2. Pick exactly 2 more projects from projects-bank.tex that best match the JD.
   - Each of the 2 additional projects gets EXACTLY 1 bullet point — pick the strongest, comment out the rest.
   - Total: exactly 3 projects, no more, no less.
   - Comment out all other projects entirely.
3. PROJECT BULLET REWRITING:
   - Apply the same language mirroring rule — use JD vocabulary in every project bullet.
   - Frame project outcomes in the company's domain language.
   - A supply chain company sees fulfillment/logistics framing; an ML company sees inference/serving framing.
4. Preserve all LaTeX formatting and hyperlinks exactly.

---

## SCORING

Score BEFORE and AFTER tailoring (0-10 each):
- keyword_match: how well resume keywords align with JD
- skills_coverage: how many required skills are present
- experience_relevance: how relevant the roles/bullets are
- projects_relevance: how well projects match the role
- overall: weighted average

Top 3 gaps using this exact format:
"GAP: [what JD wants] → FIX: [specific actionable suggestion referencing a real bullet or section]"

---

## OUTPUT FORMAT
Return ONLY valid JSON, no markdown, no extra text outside JSON:
{{
  "scoring": {{
    "before": {{"keyword_match": 7, "skills_coverage": 6, "experience_relevance": 8, "projects_relevance": 5, "overall": 6.5}},
    "after": {{"keyword_match": 9, "skills_coverage": 8, "experience_relevance": 8, "projects_relevance": 8, "overall": 8.2}},
    "gaps": [
      "GAP: JD requires Kubernetes orchestration → FIX: Reframe the Docker/Cloud Run bullet in Brightstar to mention container orchestration at scale",
      "GAP: JD emphasizes real-time inference → FIX: Add real-time framing to the RAG deployment bullet in Brightstar",
      "GAP: JD asks for A/B testing → FIX: The Uber fraud detection bullet mentions A/B testing — bold it with \\\\textbf"
    ]
  }},
  "analysis": {{
    "role_type": "...",
    "key_skills_matched": ["skill1", "skill2"],
    "projects_selected": ["project1", "project2", "project3"],
    "samsung_included": true,
    "estimated_lines": 52,
    "one_page_fit": true,
    "reasoning": "2-3 sentence summary of tailoring decisions"
  }},
  "files": {{
    "experience.tex": "...full file content...",
    "projects.tex": "...full file content..."
  }}
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5",
            # model="claude-haiku-4-5",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        diffs = {}
        for fname in ["experience.tex", "projects.tex"]:
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
    o_idx, t_idx = 0, 0

    while o_idx < len(orig_lines) or t_idx < len(tail_lines):
        o_line = orig_lines[o_idx] if o_idx < len(orig_lines) else None
        t_line = tail_lines[t_idx] if t_idx < len(tail_lines) else None

        if o_line == t_line:
            diff.append({"type": "same", "line": o_line})
            o_idx += 1
            t_idx += 1
        elif o_line is not None and t_line is not None:
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

def compile_pdf(build_dir: Path, tex_filename: str = "resume.tex") -> tuple[bool, str]:
    cmd = [
        PDFLATEX,
        "-interaction=nonstopmode",
        "-output-directory", str(build_dir),
        tex_filename  # just the filename, not full path
    ]
    log = ""
    try:
        for _ in range(2):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(build_dir)  # run FROM inside the build dir
            )
            log = result.stdout[-2000:] if result.stdout else result.stderr[-2000:]
        pdf_out = build_dir / tex_filename.replace(".tex", ".pdf")
        return pdf_out.exists(), log
    except subprocess.TimeoutExpired:
        return False, "pdflatex timed out after 60s"
    except Exception as e:
        return False, str(e)

def build_compile_dir(repo_path: str, tailored_files: dict) -> Path:
    build_dir = Path(tempfile.mkdtemp(prefix="resume_build_"))
    src_dir = build_dir / "src"
    src_dir.mkdir()

    repo = Path(repo_path)

    # Copy everything from repo root into build root
    for f in repo.glob("*.tex"):
        shutil.copy(f, build_dir / f.name)

    # Copy everything from repo src/ into build src/
    src_source = repo / "src"
    if src_source.exists():
        for f in src_source.glob("*.tex"):
            shutil.copy(f, src_dir / f.name)

    # Overwrite with tailored versions into src/
    for fname, content in tailored_files.items():
        (src_dir / fname).write_text(content)

    return build_dir

@app.route("/api/save", methods=["POST"])
def save():
    data = request.json
    files = data.get("files", {})
    company_raw = data.get("company", "Company").strip()
    role_raw = data.get("role", "Role").strip()
    company = company_raw.lower().replace(" ", "-")
    role = role_raw.lower().replace(" ", "-")
    repo_path = get_repo_path()

    if not repo_path:
        return jsonify({"error": "RESUME_REPO_PATH not set"}), 400

    date_str = datetime.now().strftime("%Y%m%d")
    folder_name = f"{company_raw.strip().title().replace(' ', '')}_{date_str}"

    output_dir = JOB_APPS_DIR / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    for fname, content in files.items():
        (output_dir / fname).write_text(content)

    manifest = {
        "company": company_raw,
        "role": role_raw,
        "date": date_str,
        "analysis": data.get("analysis", {})
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    pdf_path = None
    pdf_error = None
    try:
        build_dir = build_compile_dir(repo_path, files)
        success, log = compile_pdf(build_dir, "resume.tex")
        if success:
            pdf_src = build_dir / "resume.pdf"
            pdf_name = f"Resume_Sabari_{company_raw.strip().title().replace(' ', '')}.pdf"
            pdf_path = output_dir / pdf_name
            shutil.copy(pdf_src, pdf_path)
        else:
            pdf_error = f"pdflatex failed. Log tail: {log[-500:]}"
        shutil.rmtree(build_dir, ignore_errors=True)
    except Exception as e:
        pdf_error = str(e)

    return jsonify({
        "saved_to": str(output_dir),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "pdf_name": pdf_path.name if pdf_path else None,
        "pdf_error": pdf_error,
        "folder_name": folder_name
    })

@app.route("/api/download-pdf", methods=["POST"])
def download_pdf():
    data = request.json
    pdf_path = data.get("pdf_path")
    pdf_name = data.get("pdf_name", "resume.pdf")
    if not pdf_path or not Path(pdf_path).exists():
        return jsonify({"error": "PDF not found"}), 404
    return send_file(pdf_path, as_attachment=True, download_name=pdf_name)

@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data = request.json
    folder = data.get("folder")
    if folder and Path(folder).exists():
        subprocess.run(["open", folder])
    return jsonify({"ok": True})

@app.route("/api/history")
def history():
    if not JOB_APPS_DIR.exists():
        return jsonify([])
    entries = []
    for d in sorted(JOB_APPS_DIR.iterdir(), reverse=True):
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            m["folder"] = str(d)
            entries.append(m)
    return jsonify(entries)

@app.route("/api/preview", methods=["POST"])
def preview():
    data = request.json
    files = data.get("files", {})
    repo_path = get_repo_path()

    if not repo_path:
        return jsonify({"error": "RESUME_REPO_PATH not set"}), 400

    try:
        build_dir = build_compile_dir(repo_path, files)
        success, log = compile_pdf(build_dir, "resume.tex")
        if success:
            pdf_bytes = (build_dir / "resume.pdf").read_bytes()
            import base64
            pdf_b64 = base64.b64encode(pdf_bytes).decode()
            shutil.rmtree(build_dir, ignore_errors=True)
            return jsonify({"pdf_b64": pdf_b64})
        else:
            shutil.rmtree(build_dir, ignore_errors=True)
            return jsonify({"error": f"Compile failed: {log[-500:]}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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