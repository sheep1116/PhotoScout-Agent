import time

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_full_api(settings, brief):
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/photo-research", json=brief.model_dump(mode="json"), headers={"Idempotency-Key":"demo"})
        assert response.status_code == 202
        job = response.json()["research_id"]
        for _ in range(100):
            status = client.get(f"/v1/photo-research/{job}").json()
            if status["status"] != "running":
                break
            time.sleep(.02)
        assert status["status"] == "complete", status
        plan = client.get(f"/v1/plans/{job}").json()
        assert len(plan["tasks"]) >= 3
        assert client.post("/v1/photo-research", json=brief.model_dump(mode="json"), headers={"Idempotency-Key":"demo"}).json()["research_id"] == job
        events = client.get(f"/v1/photo-research/{job}/events")
        assert "event: done" in events.text
        proposal = client.post(f"/v1/plans/{job}/proposals", json={"task_id":plan["tasks"][0]["id"],"reason":"模拟降雨","version":1}).json()
        assert client.get(f"/v1/plans/{job}").json()["version"] == 1
        approved = client.post(f"/v1/proposals/{proposal['id']}/decision", json={"approve":True,"version":1})
        assert approved.json()["version"] == 2
        assert client.post(f"/v1/plans/{job}/undo", json={"version":2}).json()["version"] == 3


def test_missing_fields_api(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/photo-research", json={"text":"南京夜景"})
        assert response.json()["status"] == "needs_clarification"


def test_reject_cross_site_writes(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/notebook", json={}, headers={"Origin":"https://evil.com"}).status_code == 403


def test_secret_not_in_health(settings):
    from pydantic import SecretStr
    settings.dashscope_api_key = SecretStr("never-leak-test")
    with TestClient(create_app(settings)) as client:
        assert "never-leak-test" not in client.get("/v1/health").text
