"""Честный отказ там, где реализации еще нет.

Правило продукта: орган управления, за которым ничего нет, выключен и говорит
почему (`README.md`). У API это выглядит так — `501` в общем формате ошибки,
с перечнем того, чего именно не хватает.

Чего здесь принципиально нет: заглушек, возвращающих правдоподобные данные.
Мок в ответе сервера хуже отказа — фронтенд принимает его за результат,
интерфейс показывает «готово», и расхождение вскрывается не в разработке, а
у пользователя. Поэтому единственный ответ нереализованного адреса — отказ,
названный отказом.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi.responses import JSONResponse

from app.core.errors import build_error_payload

NOT_IMPLEMENTED_CODE = "not_implemented"
CONTRACT_DOC = "docs/api/README.md"


def not_implemented(
    *,
    endpoint: str,
    message: str,
    missing: Sequence[str],
    docs: str = CONTRACT_DOC,
) -> JSONResponse:
    """Ответ `501` в общем конверте ошибки.

    `missing` — не украшение. Это перечень того, чего не хватает, чтобы адрес
    заработал: по нему видно, чей это батч, а не «когда-нибудь потом».
    """
    if not missing:
        raise ValueError("Отказ обязан называть, чего не хватает: missing пустой.")
    return JSONResponse(
        status_code=501,
        content=build_error_payload(
            NOT_IMPLEMENTED_CODE,
            message,
            details={"endpoint": endpoint, "missing": list(missing), "docs": docs},
        ),
    )
