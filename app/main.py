"""需求、用例审核、缺陷及导出的 HTTP 接口。"""

import csv
from io import StringIO
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.db import connection, init_db, row_dict
from app.generation import llm_configured, llm_generate, offline_generate


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
MAX_DOCUMENT_BYTES = 200_000


class RequirementIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    kind: Literal["requirement", "openapi"] = "requirement"
    content: str = Field(min_length=8, max_length=100_000)
    source_name: str = Field(default="", max_length=160)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class GenerateIn(BaseModel):
    mode: Literal["auto", "offline", "llm"] = "auto"


class CasePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=180)
    category: Literal["normal", "boundary", "exception", "security"] | None = None
    priority: Literal["P0", "P1", "P2"] | None = None
    preconditions: str | None = Field(default=None, max_length=1500)
    steps: str | None = Field(default=None, min_length=3, max_length=3000)
    expected: str | None = Field(default=None, min_length=3, max_length=3000)
    source_ref: str | None = Field(default=None, min_length=2, max_length=500)
    review_status: Literal["draft", "approved", "rejected"] | None = None
    method: str | None = Field(default=None, max_length=10)
    path: str | None = Field(default=None, max_length=500)
    expected_http_status: int | None = Field(default=None, ge=100, le=599)


class DefectIn(BaseModel):
    requirement_id: int
    test_case_id: int | None = None
    title: str = Field(min_length=3, max_length=180)
    severity: Literal["critical", "major", "minor"] = "major"
    steps: str = Field(min_length=3, max_length=3000)
    expected: str = Field(min_length=3, max_length=3000)
    actual: str = Field(min_length=3, max_length=3000)


class DefectPatch(BaseModel):
    status: Literal["open", "fixed", "verified", "closed"]


def _requirement(conn, requirement_id: int) -> dict:
    row = conn.execute("SELECT * FROM requirements WHERE id=?", (requirement_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "需求不存在")
    return row_dict(row)


def _case(conn, case_id: int) -> dict:
    row = conn.execute("SELECT * FROM test_cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "用例不存在")
    return row_dict(row)


def _csv_cell(value) -> str:
    """避免用 Excel 打开 CSV 时将用户输入解释为公式。"""
    result = "" if value is None else str(value)
    if result.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + result
    return result


def create_app(db_path: str | Path | None = None) -> FastAPI:
    path = Path(db_path or os.getenv("TEST_WORKBENCH_DB") or ROOT / "data" / "workbench.db")
    if not path.is_absolute():
        path = ROOT / path
    init_db(path)
    app = FastAPI(title="AI 测试与缺陷工作台", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "llm_configured": llm_configured()}

    @app.post("/api/requirements", status_code=201)
    def create_requirement(payload: RequirementIn):
        if payload.kind == "openapi":
            # 预先验证结构，避免保存无法生成用例的 JSON。
            try:
                offline_generate("openapi", payload.content)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        with connection(path) as conn:
            cursor = conn.execute(
                "INSERT INTO requirements(title, kind, content, source_name) VALUES(?,?,?,?)",
                (payload.title.strip(), payload.kind, payload.content.strip(), payload.source_name),
            )
            return _requirement(conn, cursor.lastrowid)

    @app.post("/api/requirements/upload", status_code=201)
    async def upload_requirement(file: UploadFile = File(...)):
        name = Path(file.filename or "").name
        ext = Path(name).suffix.lower()
        if ext not in {".txt", ".md", ".json"}:
            raise HTTPException(400, "仅支持 .txt、.md 或 OpenAPI .json")
        raw = await file.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "文档不得超过 200 KB")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "请上传 UTF-8 编码文档") from exc
        try:
            payload = RequirementIn(title=Path(name).stem, kind="openapi" if ext == ".json" else "requirement",
                                    content=content, source_name=name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return create_requirement(payload)

    @app.get("/api/requirements")
    def list_requirements():
        with connection(path) as conn:
            rows = conn.execute("""
                SELECT r.id, r.title, r.kind, r.source_name, r.created_at,
                  (SELECT COUNT(*) FROM test_cases c WHERE c.requirement_id=r.id) AS case_count,
                  (SELECT COUNT(*) FROM test_cases c WHERE c.requirement_id=r.id AND c.review_status='approved') AS approved_count,
                  (SELECT COUNT(*) FROM defects d WHERE d.requirement_id=r.id) AS defect_count
                FROM requirements r ORDER BY r.id DESC
            """).fetchall()
            return [row_dict(row) for row in rows]

    @app.get("/api/requirements/{requirement_id}")
    def get_requirement(requirement_id: int):
        with connection(path) as conn:
            return _requirement(conn, requirement_id)

    @app.post("/api/requirements/{requirement_id}/generate")
    def generate(requirement_id: int, payload: GenerateIn):
        with connection(path) as conn:
            requirement = _requirement(conn, requirement_id)
        mode = payload.mode
        if mode == "auto":
            mode = "llm" if llm_configured() else "offline"
        try:
            cases = (llm_generate if mode == "llm" else offline_generate)(
                requirement["kind"], requirement["content"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            if mode == "llm":
                raise HTTPException(502, f"模型生成失败：{type(exc).__name__}；请检查模型服务或选择离线模式") from exc
            raise
        inserted = 0
        with connection(path) as conn:
            for case in cases:
                fields = case.model_dump()
                exists = conn.execute(
                    "SELECT 1 FROM test_cases WHERE requirement_id=? AND title=? AND source_ref=?",
                    (requirement_id, fields["title"], fields["source_ref"]),
                ).fetchone()
                if exists:
                    continue
                conn.execute("""
                    INSERT INTO test_cases(requirement_id,title,category,priority,preconditions,steps,
                      expected,source_ref,method,path,expected_http_status,generator)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (requirement_id, fields["title"], fields["category"], fields["priority"],
                      fields["preconditions"], fields["steps"], fields["expected"], fields["source_ref"],
                      fields["method"], fields["path"], fields["expected_http_status"], mode))
                inserted += 1
            conn.execute("INSERT INTO generation_runs(requirement_id,generator,case_count) VALUES(?,?,?)",
                         (requirement_id, mode, inserted))
        return {"generator": mode, "generated": len(cases), "inserted": inserted,
                "message": "生成的是待审核草稿，请核对来源、步骤和预期结果"}

    @app.get("/api/test-cases")
    def list_cases(requirement_id: int):
        with connection(path) as conn:
            _requirement(conn, requirement_id)
            rows = conn.execute("SELECT * FROM test_cases WHERE requirement_id=? ORDER BY id",
                                (requirement_id,)).fetchall()
            return [row_dict(row) for row in rows]

    @app.patch("/api/test-cases/{case_id}")
    def update_case(case_id: int, payload: CasePatch):
        data = payload.model_dump(exclude_unset=True)
        if not data or any(value is None for value in data.values()):
            raise HTTPException(400, "请提交需要修改的非空字段")
        if "method" in data:
            data["method"] = data["method"].upper()
            if data["method"] not in {"", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                raise HTTPException(400, "HTTP 方法不支持")
        with connection(path) as conn:
            _case(conn, case_id)
            fields = ", ".join(f"{key}=?" for key in data)
            conn.execute(f"UPDATE test_cases SET {fields}, updated_at=datetime('now') WHERE id=?",
                         (*data.values(), case_id))
            return _case(conn, case_id)

    @app.get("/api/requirements/{requirement_id}/cases.csv")
    def export_csv(requirement_id: int):
        with connection(path) as conn:
            _requirement(conn, requirement_id)
            rows = conn.execute("SELECT * FROM test_cases WHERE requirement_id=? AND review_status='approved' ORDER BY id",
                                (requirement_id,)).fetchall()
        if not rows:
            raise HTTPException(400, "请先审核通过至少一条用例")
        output = StringIO()
        writer = csv.writer(output)
        columns = ["id", "requirement_id", "title", "category", "priority", "preconditions", "steps",
                   "expected", "source_ref", "method", "path", "expected_http_status", "review_status"]
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_cell(row[col]) for col in columns])
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=cases-{requirement_id}.csv"})

    @app.get("/api/requirements/{requirement_id}/postman.json")
    def export_postman(requirement_id: int):
        with connection(path) as conn:
            requirement = _requirement(conn, requirement_id)
            rows = conn.execute("""
                SELECT * FROM test_cases WHERE requirement_id=? AND review_status='approved'
                  AND method!='' AND path!='' AND expected_http_status IS NOT NULL ORDER BY id
            """, (requirement_id,)).fetchall()
        if not rows:
            raise HTTPException(400, "请先审核通过并补全方法、路径及 HTTP 状态码")
        items = []
        for row in rows:
            code = row["expected_http_status"]
            items.append({
                "name": row["title"],
                "request": {"method": row["method"], "url": "{{base_url}}" + row["path"],
                            "description": f"用例 ID: {row['id']}\n来源: {row['source_ref']}\n"
                                           f"步骤: {row['steps']}\n需根据接口文档填写参数及授权信息。"},
                "event": [{"listen": "test", "script": {"type": "text/javascript",
                           "exec": [f"pm.test('HTTP {code}', function () {{",
                                    f"  pm.response.to.have.status({code});", "});"]}}],
            })
        data = {"info": {"name": f"{requirement['title']} - 已审核用例",
                         "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
                "variable": [{"key": "base_url", "value": "http://localhost:8000"}], "item": items}
        return Response(content=json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename=postman-{requirement_id}.json"})

    @app.post("/api/defects", status_code=201)
    def create_defect(payload: DefectIn):
        with connection(path) as conn:
            _requirement(conn, payload.requirement_id)
            if payload.test_case_id is not None:
                case = _case(conn, payload.test_case_id)
                if case["requirement_id"] != payload.requirement_id:
                    raise HTTPException(400, "缺陷关联的用例不属于该需求")
            cursor = conn.execute("""
                INSERT INTO defects(requirement_id,test_case_id,title,severity,steps,expected,actual)
                VALUES(?,?,?,?,?,?,?)
            """, (payload.requirement_id, payload.test_case_id, payload.title, payload.severity,
                  payload.steps, payload.expected, payload.actual))
            return row_dict(conn.execute("SELECT * FROM defects WHERE id=?", (cursor.lastrowid,)).fetchone())

    @app.get("/api/defects")
    def list_defects(requirement_id: int):
        with connection(path) as conn:
            _requirement(conn, requirement_id)
            rows = conn.execute("SELECT * FROM defects WHERE requirement_id=? ORDER BY id DESC",
                                (requirement_id,)).fetchall()
            return [row_dict(row) for row in rows]

    @app.patch("/api/defects/{defect_id}")
    def update_defect(defect_id: int, payload: DefectPatch):
        with connection(path) as conn:
            exists = conn.execute("SELECT 1 FROM defects WHERE id=?", (defect_id,)).fetchone()
            if not exists:
                raise HTTPException(404, "缺陷不存在")
            conn.execute("UPDATE defects SET status=? WHERE id=?", (payload.status, defect_id))
            return row_dict(conn.execute("SELECT * FROM defects WHERE id=?", (defect_id,)).fetchone())

    return app


app = create_app()
