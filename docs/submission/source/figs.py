import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = "/tmp/claude-0/sp/papers/fig/"
C = {"ui": "#cde2fb", "api": "#d8f0e6", "work": "#fde3d4", "store": "#fbe8b8", "ai": "#e5e0f8", "edge": "#52514e"}

def box(ax, x, y, w, h, text, color, fs=8.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=color, ec="#898781", lw=0.8))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", wrap=True)

def arrow(ax, a, b, text=None, fs=7):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=10, color=C["edge"], lw=0.9, shrinkA=2, shrinkB=2))
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.16, text, ha="center", va="bottom", fontsize=fs, color="#52514e",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

# 1. System architecture
fig, ax = plt.subplots(figsize=(11, 6.2)); ax.set_xlim(0, 10.6); ax.set_ylim(0, 6.2); ax.axis("off")
box(ax, 0.2, 5.0, 2.6, 0.9, "Browser (Next.js 16 / React 19)\nUpload · Dashboard · Chat", C["ui"], bold=True)
box(ax, 3.4, 5.0, 3.6, 0.9, "FastAPI REST API\nauth · documents · dashboard ·\nchat · analytics", C["api"], fs=8, bold=True)
box(ax, 7.8, 5.0, 2.6, 0.9, "Original files\n(data/uploads, random names)", C["store"])
box(ax, 3.4, 3.3, 3.6, 1.1, "Background worker\nparse → OCR → metadata → extract →\nvalidate → persist → chunk →\nembed → index", C["work"], fs=8, bold=True)
box(ax, 0.2, 3.3, 2.6, 1.1, "PostgreSQL 16\ndocuments · tables · metrics ·\nsource refs · chunks ·\ndashboards", C["store"], fs=8, bold=True)
box(ax, 7.8, 3.3, 2.6, 1.1, "Qdrant vector DB\n384-d BGE embeddings\npayload: owner, document", C["store"], bold=True)
box(ax, 0.2, 1.2, 3.0, 1.4, "Financial analytics (Python)\nidentity checks · ratios · growth ·\nde-duplicated facts · chart planner", C["ai"], bold=True)
box(ax, 3.7, 1.2, 3.0, 1.4, "RAG pipeline\nhybrid retrieval · basis guard ·\nrerank · M#/C#/D#/H# facts", C["ai"], bold=True)
box(ax, 7.3, 1.2, 3.1, 1.4, "Local LLM (llama.cpp)\nQwen3-4B Q4_K_M, CPU\n+ citation & number verifier", C["ai"], bold=True)
arrow(ax, (2.8, 5.45), (3.4, 5.45))
ax.text(3.1, 5.98, "HTTPS", fontsize=7, ha="center", color="#52514e")
arrow(ax, (7.0, 5.45), (7.8, 5.45), "store")
arrow(ax, (5.2, 5.0), (5.2, 4.4))
ax.text(5.3, 4.65, "job", fontsize=7, color="#52514e")
arrow(ax, (3.4, 3.85), (2.8, 3.85))
ax.text(3.1, 3.12, "facts,\nchunks", fontsize=7, ha="center", color="#52514e")
arrow(ax, (7.0, 3.85), (7.8, 3.85))
ax.text(7.4, 3.12, "vectors", fontsize=7, ha="center", color="#52514e")
arrow(ax, (1.5, 3.3), (1.5, 2.6))
arrow(ax, (9.0, 3.3), (5.6, 2.6))
ax.text(7.9, 2.75, "dense search", fontsize=7, color="#52514e")
arrow(ax, (2.2, 3.3), (4.5, 2.6))
arrow(ax, (3.2, 1.9), (3.7, 1.9))
arrow(ax, (6.7, 1.9), (7.3, 1.9))
ax.text(5.3, 0.5, "All values shown to the user come from PostgreSQL facts with a source location; arithmetic is done in Python, never by the LLM.",
        ha="center", fontsize=8, style="italic", color="#52514e")
fig.savefig(OUT + "architecture.png", dpi=200, bbox_inches="tight"); plt.close(fig)

# 2. Ingestion pipeline
steps = ["Upload &\nvalidation", "Format-specific\nparser (+OCR)", "Metadata\ndetection", "Metric\nextraction", "Validation\n(identities)",
         "Persist facts\n+ provenance", "Chunk\n(format-aware)", "Embed\n(BGE-small)", "Index\n(Qdrant)"]
fig, ax = plt.subplots(figsize=(11, 2.2)); ax.set_xlim(0, 11); ax.set_ylim(0, 2.2); ax.axis("off")
w = 1.05
for i, s in enumerate(steps):
    x = 0.15 + i * 1.2
    box(ax, x, 0.7, w, 0.95, s, [C["api"], C["work"], C["work"], C["ai"], C["ai"], C["store"], C["work"], C["ai"], C["store"]][i], fs=7.8)
    if i:
        arrow(ax, (x - 0.15, 1.17), (x, 1.17))
ax.text(5.5, 0.25, "Failure at any stage: derived rows cleared (all-or-nothing), error recorded, safe retry by reprocessing",
        ha="center", fontsize=8, style="italic", color="#52514e")
fig.savefig(OUT + "pipeline.png", dpi=200, bbox_inches="tight"); plt.close(fig)

# 3. Question answering with verification
fig, ax = plt.subplots(figsize=(10, 2.8)); ax.set_xlim(0, 10); ax.set_ylim(0, 2.8); ax.axis("off")
qs = [("Question +\ndashboard filters", C["ui"]), ("Sources:\n[S] passages  [M] values\n[C] Python calcs\n[D] dashboard  [H] scenarios", C["ai"]),
      ("LLM answer\nwith inline\ncitations", C["ai"]), ("Verifier:\ncitations exist?\nnumbers in cited\nsources? period?", C["api"]),
      ("answered /\nwith warnings /\nwithheld", C["store"])]
for i, (t, col) in enumerate(qs):
    x = 0.1 + i * 2.0
    box(ax, x, 0.6, 1.75, 1.7, t, col, fs=7.8)
    if i:
        arrow(ax, (x - 0.25, 1.45), (x, 1.45))
fig.savefig(OUT + "qa_flow.png", dpi=200, bbox_inches="tight"); plt.close(fig)

# 4. RAG regression runs (measured)
fig, ax = plt.subplots(figsize=(6, 3))
runs = ["Run 1", "Run 2", "Run 4", "Run 5"]; acc = [75.0, 87.5, 100, 100]
ax.bar(runs, acc, color="#2a78d6", width=0.55)
for i, v in enumerate(acc): ax.text(i, v + 2, f"{v:g}%", ha="center", fontsize=9)
ax.set_ylim(0, 115); ax.set_ylabel("Answer accuracy (%)"); ax.set_title("RAG answer accuracy, 8 gold questions (run 3 invalid: LLM OOM)", fontsize=9)
ax.spines[["top", "right"]].set_visible(False)
fig.savefig(OUT + "rag_runs.png", dpi=200, bbox_inches="tight"); plt.close(fig)

# 5. LoRA results (measured)
fig, ax = plt.subplots(figsize=(6.4, 3))
labels = ["Schema-valid", "Metric key", "Values exact", "Fully correct"]
base = [0, 0, 0, 0]; lora = [100, 69.3, 77.2, 69.3]
import numpy as np
x = np.arange(len(labels))
ax.bar(x - 0.18, base, 0.34, label="Base Qwen3-0.6B (zero-shot)", color="#898781")
ax.bar(x + 0.18, lora, 0.34, label="LoRA adapter", color="#1baf7a")
for i, v in enumerate(lora): ax.text(i + 0.18, v + 2, f"{v:g}%", ha="center", fontsize=8)
ax.set_xticks(x, labels, fontsize=8); ax.set_ylim(0, 115); ax.set_ylabel("% of 127 held-out rows")
ax.legend(fontsize=7, frameon=False); ax.spines[["top", "right"]].set_visible(False)
ax.set_title("LoRA fine-tuning for row-to-JSON extraction (CPU)", fontsize=9)
fig.savefig(OUT + "lora.png", dpi=200, bbox_inches="tight"); plt.close(fig)
print("figures ok")
