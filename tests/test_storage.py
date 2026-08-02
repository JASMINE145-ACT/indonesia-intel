from storage.blob import LocalBlobStore


def test_missing_blob_raises(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    try:
        store.get_bytes("missing.bin")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_blob_rejects_path_traversal(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    try:
        store.get_bytes("../secret.txt")
        assert False, "expected ValueError"
    except ValueError:
        pass
