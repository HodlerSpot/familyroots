"""Reactions and comments on Family Moments."""

from .conftest import add_child, create_family, signup
from .test_goals import make_grandparent
from .test_supporter_access import make_supporter


def _first_event_id(client, headers, family_id):
    events = client.get(f"/families/{family_id}/feed", headers=headers).json()
    return events[0]["id"]


def _add_memory(client, headers, child_id, title="A memory"):
    return client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": title},
        headers=headers,
    ).json()


def test_reaction_toggle(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _add_memory(client, parent, child_id)
    event_id = _first_event_id(client, parent, family_id)

    body = {"target_type": "feed_event", "target_id": event_id, "emoji": "❤️"}
    r = client.post("/reactions", json=body, headers=parent)
    assert r.status_code == 200, r.text
    summary = r.json()["reactions"]
    assert summary == [{"emoji": "❤️", "count": 1, "reacted": True}]

    # Toggling again removes it
    r = client.post("/reactions", json=body, headers=parent)
    assert r.json()["reactions"] == []

    # It also shows up as an at-a-glance tally on the feed
    client.post("/reactions", json=body, headers=parent)
    events = client.get(f"/families/{family_id}/feed", headers=parent).json()
    assert events[0]["reactions"][0]["emoji"] == "❤️"
    assert events[0]["reactions"][0]["count"] == 1


def test_reaction_rejects_unknown_emoji(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _add_memory(client, parent, child_id)
    event_id = _first_event_id(client, parent, family_id)

    r = client.post(
        "/reactions",
        json={"target_type": "feed_event", "target_id": event_id, "emoji": "\U0001f680"},
        headers=parent,
    )
    assert r.status_code == 400


def test_comment_flow_and_counts(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")
    _add_memory(client, parent, child_id)
    event_id = _first_event_id(client, parent, family_id)

    r = client.post(
        f"/feed-events/{event_id}/comments", json={"body": "So sweet!"}, headers=gran
    )
    assert r.status_code == 201, r.text
    assert r.json()["author_name"] == "Gran"
    assert r.json()["can_delete"] is True  # author

    comments = client.get(f"/feed-events/{event_id}/comments", headers=parent).json()
    assert len(comments) == 1
    # A parent can delete anyone's comment; the author sees can_delete too
    assert comments[0]["can_delete"] is True

    events = client.get(f"/families/{family_id}/feed", headers=parent).json()
    assert events[0]["comment_count"] == 1

    # React on the comment itself
    comment_id = comments[0]["id"]
    r = client.post(
        "/reactions",
        json={"target_type": "comment", "target_id": comment_id, "emoji": "\U0001f389"},
        headers=parent,
    )
    assert r.status_code == 200
    assert r.json()["reactions"][0]["emoji"] == "\U0001f389"


def test_comment_can_delete_matrix(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")
    relative = make_grandparent(
        client, parent, family_id, email="uncle@example.com", name="Uncle"
    )
    _add_memory(client, parent, child_id)
    event_id = _first_event_id(client, parent, family_id)

    comment_id = client.post(
        f"/feed-events/{event_id}/comments", json={"body": "hi"}, headers=gran
    ).json()["id"]

    # Another non-parent member cannot delete Gran's comment
    seen_by_relative = client.get(
        f"/feed-events/{event_id}/comments", headers=relative
    ).json()[0]
    assert seen_by_relative["can_delete"] is False
    assert client.delete(f"/comments/{comment_id}", headers=relative).status_code == 403

    # A parent can (any parent)
    assert client.delete(f"/comments/{comment_id}", headers=parent).status_code == 204
    # Soft-deleted: gone from the list
    assert client.get(f"/feed-events/{event_id}/comments", headers=parent).json() == []


def test_outsider_cannot_react_or_comment(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _add_memory(client, parent, child_id)
    event_id = _first_event_id(client, parent, family_id)

    outsider = signup(client, "outsider@example.com")
    assert client.post(
        "/reactions",
        json={"target_type": "feed_event", "target_id": event_id, "emoji": "❤️"},
        headers=outsider,
    ).status_code == 404
    assert client.post(
        f"/feed-events/{event_id}/comments", json={"body": "hi"}, headers=outsider
    ).status_code == 404


def test_supporter_cannot_touch_hidden_moment(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _add_memory(client, parent, child_id, title="Private memory")
    hidden_event_id = _first_event_id(client, parent, family_id)

    supporter = make_supporter(client, parent, family_id)
    # The unshared memory isn't visible to the supporter → treated as not found
    assert client.post(
        "/reactions",
        json={
            "target_type": "feed_event",
            "target_id": hidden_event_id,
            "emoji": "❤️",
        },
        headers=supporter,
    ).status_code == 404
    assert client.post(
        f"/feed-events/{hidden_event_id}/comments", json={"body": "hi"}, headers=supporter
    ).status_code == 404

    # ...but a supporter may react on their own member_joined moment
    join_event = [
        e
        for e in client.get(f"/families/{family_id}/feed", headers=supporter).json()
        if e["type"] == "member_joined"
    ][0]
    assert client.post(
        "/reactions",
        json={
            "target_type": "feed_event",
            "target_id": join_event["id"],
            "emoji": "\U0001f389",
        },
        headers=supporter,
    ).status_code == 200
