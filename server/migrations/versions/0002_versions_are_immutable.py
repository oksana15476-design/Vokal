"""Неизменяемость версии аранжировки держит база.

Версия — запись истории: что изменилось, кто это сделал и какие материалы
были на руках. Если такую запись можно переписать одним `UPDATE`, история
перестает отвечать на единственный вопрос, ради которого ведется, — почему
материалы стали такими. Откат в продукте потому и создает **новую** версию, а
не правит старую; триггер закрывает обход этого правила мимо сервисного слоя.

Что разрешено и почему:

* `deleted_at` и `retention_until` — мягкое удаление и срок хранения. Пометить
  запись удаленной не значит переписать ее содержание, а без этого перестал бы
  работать каскад удаления песни.
* `artifacts_snapshot` **только в NULL**. Удаление результатов уносит снимок
  вместе с материалами (`docs/DELETION_AND_RETENTION_DESIGN.md`: история версий
  остается перечнем изменений без самих файлов). Заменить снимок другим нельзя:
  это и была бы подмена состояния, на которое ссылается откат.

Все остальное — подпись, вид, родитель, автор, время, перечень изменений и
статус — после вставки не меняется никогда.

Известное ограничение: `versions.parent_version_id` объявлен с
`ON DELETE SET NULL`. Физического удаления строк в продукте нет вовсе
(`app/db/retention.py` отказывается его изображать), но если оно появится,
каскадное обнуление родителя упрется в этот триггер — и это правильное место
для разговора, а не тихое переписывание истории.

Revision ID: 0002_versions_are_immutable
Revises: 0001_initial_schema
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_versions_are_immutable"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vokal_version_is_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.project_id IS DISTINCT FROM OLD.project_id
                OR NEW.parent_version_id IS DISTINCT FROM OLD.parent_version_id
                OR NEW.label IS DISTINCT FROM OLD.label
                OR NEW.kind IS DISTINCT FROM OLD.kind
                OR NEW.status IS DISTINCT FROM OLD.status
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.changes IS DISTINCT FROM OLD.changes
            THEN
                RAISE EXCEPTION
                    'Версия неизменяема: правка истории запрещена, откат создает новую версию'
                    USING ERRCODE = '23514';
            END IF;

            -- Очисткой считается и SQL NULL, и json-значение null: драйвер
            -- пишет в JSONB именно 'null', а не NULL колонки, и без этой
            -- проверки удаление результатов упиралось бы в триггер.
            IF NEW.artifacts_snapshot IS DISTINCT FROM OLD.artifacts_snapshot
                AND NEW.artifacts_snapshot IS NOT NULL
                AND jsonb_typeof(NEW.artifacts_snapshot) <> 'null'
            THEN
                RAISE EXCEPTION
                    'Снимок материалов версии можно только стереть при удалении результатов'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER versions_are_immutable
        BEFORE UPDATE ON versions
        FOR EACH ROW EXECUTE FUNCTION vokal_version_is_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS versions_are_immutable ON versions")
    op.execute("DROP FUNCTION IF EXISTS vokal_version_is_immutable()")
