from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware
import json
import uvicorn
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from graph_processor import create_notebook_processor, NotebookState

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SAVE_DIR = Path("processed_notebooks")
SAVE_DIR.mkdir(exist_ok=True)

analysis_queue = asyncio.Queue()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/process-notebook/")
async def process_notebook(data: dict):
    try:
        cells = data.get("cells", [])
        excluded_indices = set(data.get("excludedIndices", []))

        processed_cells = []
        for idx, cell in enumerate(cells):
            if idx not in excluded_indices:
                cell_info = {
                    "cell_number": len(processed_cells) + 1,
                    "cell_type": cell["cell_type"],
                    "content": (
                        "".join(cell["source"])
                        if isinstance(cell["source"], list)
                        else cell["source"]
                    ),
                }
                if cell["cell_type"] == "code" and "outputs" in cell:
                    outputs = []
                    for output in cell["outputs"]:
                        if "text" in output:
                            outputs.append(
                                {
                                    "type": "text/plain",
                                    "data": (
                                        "".join(output["text"])
                                        if isinstance(output["text"], list)
                                        else output["text"]
                                    ),
                                }
                            )
                        elif "data" in output and "text/plain" in output["data"]:
                            outputs.append(
                                {
                                    "type": "text/plain",
                                    "data": (
                                        "".join(output["data"]["text/plain"])
                                        if isinstance(
                                            output["data"]["text/plain"], list
                                        )
                                        else output["data"]["text/plain"]
                                    ),
                                }
                            )
                    cell_info["outputs"] = outputs
                processed_cells.append(cell_info)

        # 결과를 파일로 저장
        result = {"cells": processed_cells}
        file_path = SAVE_DIR / "processed_notebook.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return JSONResponse(
            content={"cells": processed_cells, "file_path": str(file_path)}
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/generate-blog")
async def generate_blog():
    try:
        # JSON 파일 읽기
        file_path = SAVE_DIR / "processed_notebook.json"
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 초기 상태 설정
        initial_state = {
            "cells": data["cells"],
            "cell_groups": [],
            "analyzed_groups": [],
            "blog_sections": [],
        }

        # 분석 진행 상황을 스트리밍하기 위한 콜백
        # main.py의 generate_blog 함수 내부
        async def stream_callback(state, step):
            try:
                if step in ["grouping", "analyzing", "generating", "complete"]:
                    await analysis_queue.put({"type": "status", "step": step})
                elif step == "content":
                    await analysis_queue.put(
                        {
                            "type": "content",
                            "data": {"content": state.get("content", "")},
                        }
                    )
            except Exception as e:
                print(f"Callback error: {str(e)}")  # 디버깅용

        try:
            # 그래프 프로세서 생성 및 실행
            processor = create_notebook_processor(stream_callback)

            # 시작 상태 전송
            await analysis_queue.put({"type": "status", "step": "start"})

            # 처리 실행
            result = await processor.ainvoke(initial_state)

            return StreamingResponse(stream_analysis(), media_type="text/event-stream")

        except Exception as process_error:
            print(f"처리 중 에러 발생: {str(process_error)}")
            await analysis_queue.put({"type": "error", "message": str(process_error)})
            raise HTTPException(status_code=500, detail=str(process_error))

    except Exception as e:
        print(f"전체 에러: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


async def stream_analysis():
    """분석 결과를 스트리밍"""
    try:
        while True:
            data = await analysis_queue.get()
            if isinstance(data, dict):
                # 간단한 로그만 출력
                if data["type"] == "status":
                    print(f"Status: {data['step']}")
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
