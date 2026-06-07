from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from model_analysis.core.config import ASSET_DIR  # noqa: E402
from model_analysis.expert.skill import analyze_with_3d_expert_skill  # noqa: E402
from model_analysis.services.analysis_runner import run_model_analysis  # noqa: E402
from model_analysis.services.quality import quality_status_from_analysis  # noqa: E402

SAMPLE_MODELS = [
    PROJECT_ROOT / "samples" / "models" / "tripo_rigging_a664b53f-caef-40fb-8c1f-f65976576f70.fbx",
    PROJECT_ROOT / "samples" / "models" / "iridescent hummingbird 3d model.glb",
]


async def analyze_sample(file_path: Path, index: int) -> dict:
    task_id = f"sample-smoke-{index}"
    asset_dir = ASSET_DIR / task_id
    shutil.rmtree(asset_dir, ignore_errors=True)
    engine, analysis = await run_model_analysis(file_path, asset_dir, task_id)
    standard = quality_status_from_analysis(analysis)
    expert = analyze_with_3d_expert_skill(analysis, standard)["expert_analysis"]
    return {
        "file": file_path.name,
        "engine": engine,
        "summary": analysis.get("summary") if isinstance(analysis, dict) else None,
        "structure_conclusion": expert.get("structure_conclusion"),
        "texture_resolution_summary": expert.get("texture_resolution_summary", [])[:8],
        "impact_analysis": expert.get("impact_analysis", []),
    }


async def main() -> None:
    results = []
    for index, file_path in enumerate(SAMPLE_MODELS, 1):
        if not file_path.exists():
            results.append({"file": str(file_path), "error": "sample model not found"})
            continue
        try:
            results.append(await analyze_sample(file_path, index))
        except Exception as exc:
            results.append({"file": file_path.name, "error": str(exc)})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
