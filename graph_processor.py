from typing import Annotated, List, Tuple, Dict
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain_core.output_parsers import StrOutputParser
import asyncio
import json


# 상태 정의
class NotebookState(TypedDict):
    cells: Annotated[List[dict], "Notebook cells"]
    cell_groups: Annotated[List[Dict], "Grouped cells"]
    analyzed_groups: Annotated[List[Dict], "Analyzed cell groups"]
    blog_sections: Annotated[List[Dict], "Generated blog sections"]


# 셀 그룹 분류 모델
class CellGroups(BaseModel):
    """Cell grouping for analysis"""

    groups: List[Dict] = Field(
        description="Groups of related cells with start and end indices"
    )


# 셀 그룹화 프롬프트
group_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        # 노트북의 셀들을 효과적인 설명을 위한 의미 있는 그룹으로 나누어주세요.
        
        # 다음 기준으로 그룹을 나누세요:
        1. 주요 클래스/함수: 핵심 기능을 구현하는 코드 그룹
        2. 유틸리티/헬퍼: 보조 기능을 담당하는 코드 그룹
        3. 실행 및 데모: 실제 사용 예시와 결과를 보여주는 부분
        
        # 마크다운 셀과 코드 셀의 연관성을 고려하여 그룹화하세요.
        각 그룹은 독자가 따라하며 이해할 수 있는 단위여야 합니다.
        
        # 각 그룹에 대해 다음 정보를 제공하세요:
        - start_idx: 그룹의 시작 셀 인덱스
        - end_idx: 그룹의 마지막 셀 인덱스
        - purpose: 이 그룹이 설명하는 기능과 독자가 얻을 수 있는 인사이트
        - title: 그룹을 대표하는 제목
        
        # 다음과 같은 JSON 형식으로 반환해주세요:
        {{
            "groups": [
                {{
                    "start_idx": 0,
                    "end_idx": 2,
                    "purpose": "프로젝트의 목적과 사용할 주요 라이브러리 소개",
                    "title": "프로젝트 소개 및 환경 설정"
                }},
                ...
            ]
        }}""",
        ),
        (
            "user",
            "다음 노트북 셀들을 분석하여 의미 있는 그룹으로 나누어주세요:\n{cell_contents}",
        ),
    ]
)

# 그룹 분석 프롬프트
analyzer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        # 당신은 코딩 블로그 작성자입니다. 블로그을 작성하기전에 주어진 코드 그룹을 분석하여 학습한 내용에 대해서 다른 사람도 이해하기 쉽게 정리한 대본을 만드는일을 합니다.
        
        ## 기본적인 구조 : 사용된 코드 - 설명

        ## 설명을 작성할때 참고할 내용 :
        1. 코드의 목적과 동작 원리
           - 이 코드가 필요한 이유
           - 전체적인 로직의 흐름
        
        2. 주요 구현 내용 설명
           - 핵심 코드 부분 강조
           - 중요 변수/함수의 역할
           - 사용된 라이브러리/기술의 특징
        
        3. 구현의 특이사항
           - 주의해야 할 부분
           - 예시 데이터가 있을시 데이터 타입의 맞게 설명
        
        
        마크다운 설명과 코드를 연계하여 분석하고 작성해야하는데 그룹안에 코드들이 비슷한 내용이면 묶어서 설명해주세요
        # 단 사용된 코드는 빠짐 없이 작성되어야합니다  
            """,
        ),
        (
            "user",
            """다음 코드 그룹을 분석해주세요:
        제목: {title}
        목적: {purpose}
        
        코드:
        {code_content}""",
        ),
    ]
)

# 블로그 생성 프롬프트
blog_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
        # 당신은 코딩 블로그 작성자입니다. 분석된 코드 그룹의 대본을 바탕으로 하나의 완성된 기술 블로그 포스트를 작성해주세요.
        
        # 다음 구조로 작성하세요:
        1. 소개 (프리뷰)
           - 오늘 작성하게될 기술들이 간단한 기술 설명
           - 사용된 주요 기술과 선택 이유(추천이유) 
        
        2. 본문 (각 그룹의 분석 내용을 자연스럽게 연결)
           - 그룹 간의 논리적 흐름 유지
           - 무조건 사용된 코드 작성후 설명 작성 
        
        3. 마무리
           - 문제가 있었을시 자신이 어떠한 과정을 거쳐서 문제를 해결했는가
           - 전체 내용 요약

        
        # 작성 시 주의사항:
        - 각 그룹의 내용을 단순 나열하지 말고 자연스럽게 연결하세요
        - 실제 사용자가 따라할 수 있도록 구체적으로 작성하세요
        - 각 섹션이 자연스럽게 이어지도록 적절한 전환구를 사용하세요""",
        ),
        (
            "user",
            "다음 분석된 그룹들을 바탕으로 블로그 포스트를 작성해주세요:\n{analysis_content}",
        ),
    ]
)


def group_cells(state: NotebookState):
    """노트북 셀들을 의미 있는 그룹으로 분류"""
    cell_contents = "\n\n".join(
        [
            f"Cell {i+1} ({cell['cell_type']}):\n{cell['content']}"
            for i, cell in enumerate(state["cells"])
        ]
    )

    grouper = group_prompt | ChatOpenAI(
        temperature=0, model_name="gpt-4o", max_tokens=15000, streaming=True
    ).with_structured_output(CellGroups)
    result = grouper.invoke({"cell_contents": cell_contents})

    return {"cell_groups": result.groups}


def analyze_groups(state: NotebookState):
    """각 셀 그룹 분석"""
    groups = state["cell_groups"]
    analyzed_groups = []

    analyzer = analyzer_prompt | ChatOpenAI(
        temperature=0, model_name="gpt-4o", max_tokens=15000, streaming=True
    )

    for group in groups:
        start_idx = group["start_idx"]
        end_idx = group["end_idx"]

        # 그룹에 속한 셀들의 내용 추출
        group_cells = state["cells"][start_idx : end_idx + 1]
        code_content = "\n\n".join(
            [
                f"Cell {i+start_idx+1}:\n{cell['content']}"
                for i, cell in enumerate(group_cells)
            ]
        )

        analysis = analyzer.invoke(
            {
                "title": group["title"],
                "purpose": group["purpose"],
                "code_content": code_content,
            }
        )

        analyzed_groups.append(
            {
                **group,
                "analysis": (
                    analysis.content if hasattr(analysis, "content") else analysis
                ),
            }
        )

    return {"analyzed_groups": analyzed_groups}


def generate_blog_post(state: NotebookState):
    """분석된 그룹들을 바탕으로 섹션별 블로그 포스트 생성"""
    analyzed_groups = state["analyzed_groups"]
    blog_sections = []

    blog_generator = blog_prompt | ChatOpenAI(
        temperature=0.7, model_name="gpt-4o", max_tokens=15000, streaming=True
    )

    # 각 그룹별로 개별적인 블로그 섹션 생성
    for group in analyzed_groups:
        analysis_content = f"섹션: {group['title']}\n목적: {group['purpose']}\n분석:\n{group['analysis']}"
        result = blog_generator.invoke({"analysis_content": analysis_content})
        blog_sections.append(
            {
                "title": group["title"],
                "content": result.content if hasattr(result, "content") else result,
            }
        )

    return {"blog_sections": blog_sections}


def create_notebook_processor(stream_callback=None):
    """스트리밍 지원을 포함한 노트북 프로세서 생성"""
    workflow = StateGraph(NotebookState)

    async def group_cells_with_stream(state: NotebookState):
        """셀 그룹화 with 스트리밍"""
        if stream_callback:
            await stream_callback(
                {"status": "grouping", "total": len(state["cells"])}, "grouping"
            )
        result = group_cells(state)
        return result

    async def analyze_groups_with_stream(state: NotebookState):
        """그룹 분석 with 스트리밍"""
        if stream_callback:
            await stream_callback(
                {"status": "analyzing", "total": len(state["cell_groups"])}, "analyzing"
            )
        result = analyze_groups(state)
        return result

    async def generate_blog_with_stream(state: NotebookState):
        """블로그 생성 with 스트리밍"""
        if stream_callback:
            await stream_callback(
                {"status": "generating", "total": len(state["analyzed_groups"])},
                "generating",
            )

        blog_generator = blog_prompt | ChatOpenAI(
            temperature=0.7, model_name="gpt-4o", max_tokens=4000, streaming=True
        )

        analyzed_content = "\n\n".join(
            [
                f"섹션: {group['title']}\n목적: {group['purpose']}\n분석:\n{group['analysis']}"
                for group in state["analyzed_groups"]
            ]
        )

        full_content = ""
        async for chunk in blog_generator.astream(
            {"analysis_content": analyzed_content}
        ):
            if chunk.content:
                full_content += chunk.content
                if stream_callback:
                    await stream_callback({"content": full_content}, "content")

        result = {"blog_sections": [{"content": full_content}]}

        if stream_callback:
            await stream_callback({"status": "complete", "total": 1}, "complete")

        return result

    workflow.add_node("group", group_cells_with_stream)
    workflow.add_node("analyze", analyze_groups_with_stream)
    workflow.add_node("blog", generate_blog_with_stream)

    workflow.add_edge(START, "group")
    workflow.add_edge("group", "analyze")
    workflow.add_edge("analyze", "blog")
    workflow.add_edge("blog", END)

    return workflow.compile()
