import logging

logger = logging.getLogger(__name__)
_seen = set()


def clear_render_log_dedup() -> None:
    _seen.clear()


def log_render_failure(kind, entity, root, error, config_path=None) -> bool:
    key = (kind, str(entity), str(root), str(config_path or ""))
    if key in _seen:
        return False
    if len(_seen) >= 128:
        _seen.clear()
    _seen.add(key)
    logger.error("渲染失败 kind=%s id=%s root=%s config=%s",
                 kind, entity, root, config_path or "-", exc_info=True)
    return True
