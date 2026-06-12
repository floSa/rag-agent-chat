from src.agent.minio_client import object_name_from_url, to_media_path


def test_object_name_from_url() -> None:
    url = "http://minio:9000/documents/images/livre/abc123def0_picture.png"
    assert object_name_from_url(url) == "images/livre/abc123def0_picture.png"


def test_object_name_from_url_unrecognized() -> None:
    # Pas de chemin objet après le bucket
    assert object_name_from_url("http://minio:9000/documents") is None


def test_to_media_path() -> None:
    url = "http://minio:9000/documents/images/livre/abc123def0_picture.png"
    assert to_media_path(url) == "/media/images/livre/abc123def0_picture.png"


def test_to_media_path_unrecognized_passthrough() -> None:
    # URL non reconnue : retournée telle quelle plutôt que cassée
    assert to_media_path("http://example.com/foo") == "http://example.com/foo"
