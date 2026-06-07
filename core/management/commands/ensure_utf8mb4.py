"""Convert MySQL database and tables to utf8mb4 (required for emoji in assistant chat)."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        'Convert MySQL database/tables to utf8mb4 so emoji (e.g. ticket icons) can be stored. '
        'Run once on production after deploying utf8mb4 DB settings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--database',
            default='default',
            help='Database alias from DATABASES (default: default)',
        )

    def handle(self, *args, **options):
        db_alias = options['database']
        db = settings.DATABASES.get(db_alias, {})
        engine = db.get('ENGINE', '')

        if 'mysql' not in engine:
            self.stdout.write(self.style.WARNING(
                f'Database engine is {engine or "unknown"} — nothing to do (MySQL only).'
            ))
            return

        db_name = db.get('NAME')
        if not db_name:
            self.stderr.write(self.style.ERROR('DB_NAME is not configured.'))
            return

        with connection.cursor() as cursor:
            cursor.execute(
                f'ALTER DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
            )
            self.stdout.write(f'Altered database `{db_name}` to utf8mb4.')

            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
                """,
                [db_name],
            )
            tables = [row[0] for row in cursor.fetchall()]

            for table in tables:
                cursor.execute(
                    f'ALTER TABLE `{table}` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
                )
                self.stdout.write(f'  {table}')

        self.stdout.write(self.style.SUCCESS(
            f'Converted {len(tables)} table(s) to utf8mb4. Restart the app if it was running.'
        ))
