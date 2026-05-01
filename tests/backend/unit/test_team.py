import pytest

def test_get_teams_empty(client):
    response = client.get("/api/teams")
    assert response.status_code == 200
    assert response.json() == []

def test_get_teams_with_data(client, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('zone1', 'Zone 1')")
    db_conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('team1', 'Team 1', 'hash', 'zone1')")
    db_conn.commit()
    
    response = client.get("/api/teams")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "team1"
    assert data[0]["name"] == "Team 1"
    assert data[0]["zone_id"] == "zone1"

def test_get_zone_teams(client, admin_auth, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('zone2', 'Zone 2')")
    db_conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('team2', 'Team 2', 'hash', 'zone2')")
    db_conn.commit()
    
    response = client.get("/api/admin/zones/zone2/teams", headers=admin_auth)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "team2"
    assert data[0]["name"] == "Team 2"

def test_register_team(client, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('zone3', 'Zone 3')")
    db_conn.commit()
    
    response = client.post("/api/register", json={
        "zone_id": "zone3",
        "team_id": "new_team",
        "team_name": "New Team",
        "password": "password123"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "registered"
    
    row = db_conn.execute("SELECT * FROM teams WHERE id='new_team'").fetchone()
    assert row is not None
    assert row["name"] == "New Team"
    assert row["zone_id"] == "zone3"

def test_register_team_invalid_id(client, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('zone4', 'Zone 4')")
    db_conn.commit()
    
    response = client.post("/api/register", json={
        "zone_id": "zone4",
        "team_id": "invalid id!",
        "team_name": "Invalid Team",
        "password": "password123"
    })
    
    assert response.status_code == 400
    assert "队伍ID只允许字母/数字/下划线" in response.json()["detail"]
