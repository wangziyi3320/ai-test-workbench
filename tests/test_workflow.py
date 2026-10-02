import csv
from io import StringIO
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from app.generation import llm_generate
from app.main import create_app


@pytest.fixture
def client():
    path = Path(__file__).resolve().parent.parent / "data" / f"test-{uuid4().hex}.db"
    with TestClient(create_app(path)) as test_client:
        yield test_client
    path.unlink(missing_ok=True)


def test_requirement_review_export_and_defect_workflow(client):
    content = "- 用户输入合法网址后可以创建短链。\n- 自定义短码长度为 4 至 12 个字符。"
    created = client.post("/api/requirements", json={"title": "短链需求", "content": content})
    assert created.status_code == 201
    req_id = created.json()["id"]

    first = client.post(f"/api/requirements/{req_id}/generate", json={"mode": "offline"})
    assert first.status_code == 200
    assert first.json()["inserted"] == 3
    assert first.json()["generator"] == "offline"
    assert client.post(f"/api/requirements/{req_id}/generate", json={"mode": "offline"}).json()["inserted"] == 0
    cases = client.get(f"/api/test-cases?requirement_id={req_id}").json()
    assert all(item["review_status"] == "draft" for item in cases)
    assert any(item["category"] == "boundary" for item in cases)
    assert client.get(f"/api/requirements/{req_id}/cases.csv").status_code == 400

    case_id = cases[0]["id"]
    edited = client.patch(f"/api/test-cases/{case_id}", json={
        "steps": "输入合法网址，点击生成按钮。", "expected": "生成短链并出现在列表中。",
        "review_status": "approved", "title": "=HYPERLINK(\"bad\")",
    })
    assert edited.status_code == 200
    assert edited.json()["review_status"] == "approved"
    exported = client.get(f"/api/requirements/{req_id}/cases.csv")
    assert exported.status_code == 200
    csv_content = exported.content.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(csv_content)))
    assert len(rows) == 1
    assert rows[0]["title"].startswith("'=HYPERLINK")

    other = client.post("/api/requirements", json={"title": "另一需求", "content": "用户可查询短链列表。"}).json()
    mismatch = client.post("/api/defects", json={
        "requirement_id": other["id"], "test_case_id": case_id, "title": "错误关联的缺陷",
        "steps": "进入页面", "expected": "有结果", "actual": "出现错误", "severity": "major",
    })
    assert mismatch.status_code == 400
    created_defect = client.post("/api/defects", json={
        "requirement_id": req_id, "test_case_id": case_id, "title": "合法网址生成失败",
        "steps": "输入网址后点击生成", "expected": "出现短链", "actual": "返回服务错误", "severity": "major",
    })
    assert created_defect.status_code == 201
    defect_id = created_defect.json()["id"]
    assert client.patch(f"/api/defects/{defect_id}", json={"status": "fixed"}).json()["status"] == "fixed"
    assert len(client.get(f"/api/defects?requirement_id={req_id}").json()) == 1


def test_openapi_upload_and_postman_export(client):
    spec = {
        "openapi": "3.0.3", "info": {"title": "样例", "version": "1.0"},
        "paths": {"/api/links": {"post": {
            "summary": "创建短链", "parameters": [{"name": "tenant", "in": "header", "required": True,
                                           "schema": {"type": "string"}}],
            "responses": {"201": {"description": "已创建"}, "400": {"description": "无效请求"}},
        }}},
    }
    uploaded = client.post("/api/requirements/upload", files={"file": ("sample.json", json.dumps(spec).encode(), "application/json")})
    assert uploaded.status_code == 201
    req_id = uploaded.json()["id"]
    assert uploaded.json()["kind"] == "openapi"
    generated = client.post(f"/api/requirements/{req_id}/generate", json={"mode": "offline"})
    assert generated.json()["inserted"] == 2
    cases = client.get(f"/api/test-cases?requirement_id={req_id}").json()
    success = next(case for case in cases if case["category"] == "normal")
    assert success["expected_http_status"] == 201
    assert client.get(f"/api/requirements/{req_id}/postman.json").status_code == 400
    assert client.patch(f"/api/test-cases/{success['id']}", json={"review_status": "approved"}).status_code == 200
    collection = client.get(f"/api/requirements/{req_id}/postman.json")
    assert collection.status_code == 200
    item = collection.json()["item"][0]
    assert item["request"]["method"] == "POST"
    assert item["request"]["url"] == "{{base_url}}/api/links"
    assert "status(201)" in "\n".join(item["event"][0]["script"]["exec"])
    assert "填写参数及授权" in item["request"]["description"]


def test_invalid_openapi_and_oversized_upload_are_rejected(client):
    bad = client.post("/api/requirements", json={"title": "错误接口文档", "kind": "openapi", "content": "{bad json}"})
    assert bad.status_code == 400
    malformed = client.post("/api/requirements", json={"title": "错误接口定义", "kind": "openapi",
        "content": json.dumps({"paths": {"/links": {"post": {"parameters": None}}}})})
    assert malformed.status_code == 400
    huge = client.post("/api/requirements/upload", files={"file": ("huge.txt", b"a" * 200_001, "text/plain")})
    assert huge.status_code == 413


def test_llm_adapter_validates_grounding(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "demo")
    monkeypatch.setenv("LLM_API_KEY", "test-only-placeholder")
    source = "用户输入合法网址后可以创建短链。"
    generated = {
        "cases": [{"title": "验证创建短链", "category": "normal", "priority": "P1",
                   "steps": "输入合法网址并提交", "expected": "显示生成的短链",
                   "source_ref": source}]}
    original_client = httpx.Client

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "demo"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(generated)}}]})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    assert llm_generate("requirement", source)[0].source_ref == source
    generated["cases"][0]["source_ref"] = "不存在的需求"
    with pytest.raises(ValueError, match="无法在原需求中定位"):
        llm_generate("requirement", source)
    with pytest.raises(ValueError, match="20000 字符上限"):
        llm_generate("requirement", "需" * 20_001)
    generated["cases"][0].update({"source_ref": "GET /links", "method": "GET", "path": "/links"})
    with pytest.raises(ValueError, match="未在接口文档中声明的方法"):
        llm_generate("openapi", json.dumps({"paths": {"/links": {"post": {"responses": {"201": {}}}}}}))
