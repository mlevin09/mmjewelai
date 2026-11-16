# Foundation текущих ролей (RU TRANSLATION)

Шестиролевой JSON runtime заменён текущим PostgreSQL-каталогом.
См. [ADR 0044](../../docs/adr/0044-postgresql-current-roles.ru.md) и
[API/import contract](../../docs/architecture/CURRENT_ROLES_API.ru.md).
`schema.json` описывает одно текущее определение; исходные исторические спецификации
сохраняются в Git history, не в исполняемом fallback-каталоге.
