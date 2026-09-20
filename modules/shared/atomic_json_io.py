import io
import json
import os
import tempfile


def _make_path_writable(path):
    if not os.path.exists(path):
        return
    try:
        os.chmod(path, 0o644)
    except Exception:
        pass
    if hasattr(os, "chflags"):
        try:
            os.chflags(path, 0)
        except Exception:
            pass


def atomic_write_json(path, payload, preserve_existing=True, encoder_cls=None):
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)

    payload_buffer = io.StringIO()
    dump_kwargs = {"indent": 2, "ensure_ascii": False}
    if encoder_cls is not None:
        dump_kwargs["cls"] = encoder_cls
    json.dump(payload, payload_buffer, **dump_kwargs)
    payload_text = payload_buffer.getvalue()

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=dir_name,
            delete=False,
            encoding="utf-8",
        ) as tf:
            temp_name = tf.name
            tf.write(payload_text)

        try:
            os.replace(temp_name, path)
        except OSError:
            _make_path_writable(path)
            try:
                os.replace(temp_name, path)
            except OSError:
                if preserve_existing and os.path.exists(path):
                    raise
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(payload_text)
            finally:
                if temp_name and os.path.exists(temp_name):
                    os.remove(temp_name)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)
