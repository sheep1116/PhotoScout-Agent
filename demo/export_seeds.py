"""Export both honest offline demos without starting a server or using API keys."""
import asyncio
from pathlib import Path

from backend.app.config import Settings
from backend.app.graph import run_graph
from backend.app.models import Lens, TripBrief

ROOT = Path(__file__).resolve().parents[1]


async def main():
    folder = ROOT / "demo/output"
    folder.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, dashscope_api_key="", amap_web_service_key="")
    async def emit(stage, message):
        print(stage)
    for genre in ["portrait", "cityscape"]:
        brief = TripBrief(destination="南京紫金山" if genre == "portrait" else "南京", genre=genre,
            travel_date="2026-10-03", start_local="14:00", end_local="21:00", tripod=genre == "cityscape",
            lenses=[Lens(name="35mm F1.8",min_mm=35,max_mm=35,max_aperture=1.8)])
        plan = await run_graph("demo-"+genre, brief, settings, emit)
        (folder/f"{genre}.json").write_text(plan.model_dump_json(indent=2),encoding="utf-8")
    print("Exported portrait and cityscape fixtures to demo/output/ (not real-world advice).")


if __name__ == "__main__":
    asyncio.run(main())
