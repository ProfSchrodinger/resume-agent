# Resume Tailoring Agent

A local web app that tailors your LaTeX resume for specific job descriptions using Claude AI.

## Quick Start

```bash
cd resume-agent
chmod +x run.sh
./run.sh
```

Then open http://localhost:5000

## Manual Start

```bash
pip install flask anthropic

export RESUME_REPO_PATH=~/Documents/resume-latex
export ANTHROPIC_API_KEY=sk-ant-...

python app.py
```

## How It Works

1. Paste a job description + company + role
2. Agent analyses the JD, selects best projects, rewrites bullets
3. Review the diff — see exactly what changed
4. Approve → files saved to `tailored/<company>_<role>_<date>/` + zip downloaded
5. Upload zip to Overleaf to compile PDF

## File Structure Expected

```
resume-latex/
├── src/
│   ├── experience.tex
│   ├── projects.tex
│   ├── projects-bank.tex   ← all projects, agent reads from here
│   ├── skills.tex
│   ├── activities.tex
│   ├── heading.tex
│   └── education.tex
├── custom-commands.tex
├── resume.tex
└── tailored/               ← agent saves here
    └── google_data-scientist_20250522/
        ├── experience.tex
        ├── projects.tex
        ├── skills.tex
        └── manifest.json
```

## Syncing with Overleaf

Since you're on free Overleaf, sync manually:

```bash
# After editing in Overleaf: download Source zip, then:
cp ~/Downloads/resume-latex/src/*.tex ~/Documents/resume-latex/src/
git add . && git commit -m "sync from overleaf" && git push
```

## Using a Tailored Resume in Overleaf

1. Download the zip from the agent after approving
2. In Overleaf: New Project → Upload Project → upload the zip
3. Compile and export PDF
