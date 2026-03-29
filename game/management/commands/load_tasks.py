import json
from pathlib import Path

from django.core.management.base import BaseCommand

from game.models import Task, TaskAnswer, TaskImage

SUBJECT_MAP = {
    'Математика': 'math',
    'Русский': 'russian',
    'Русский язык': 'russian',
    'Физика': 'physics',
    'Химия': 'chemistry',
    'Биология': 'biology',
    'История': 'history',
    'Обществознание': 'social',
    'Информатика': 'informatics',
    'Английский': 'english',
    'Английский язык': 'english',
    'География': 'geography',
    'Литература': 'literature',
}


class Command(BaseCommand):
    help = 'Загрузка задач из JSON-файлов в БД'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', nargs='+', type=str,
            help='Пути к JSON-файлам с задачами',
        )
        parser.add_argument(
            '--dir', type=str,
            help='Директория с JSON-файлами задач',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Удалить все существующие задачи перед загрузкой',
        )

    def handle(self, *args, **options):
        if options['clear']:
            count = Task.objects.count()
            Task.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Удалено {count} задач'))

        files = []
        if options['file']:
            files = [Path(f) for f in options['file']]
        elif options['dir']:
            d = Path(options['dir'])
            files = sorted(d.glob('*.json'))

        if not files:
            self.stdout.write(self.style.ERROR('Не указаны файлы. Используйте --file или --dir'))
            return

        total_created = 0
        for filepath in files:
            count = self._load_file(filepath)
            total_created += count
            self.stdout.write(f'  {filepath.name}: загружено {count} задач')

        self.stdout.write(self.style.SUCCESS(f'Всего загружено: {total_created} задач'))

    def _load_file(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        created = 0
        for item in data:
            subject = SUBJECT_MAP.get(item.get('subject', ''), item.get('subject', ''))
            difficulty = item.get('difficulty', 1)
            difficulty = max(1, min(5, difficulty))

            answers = item.get('answer', [])
            correct_answer = '|'.join(str(a) for a in answers) if answers else None

            task = Task.objects.create(
                text=item.get('text', ''),
                correct_answer=correct_answer,
                difficulty=difficulty,
                subject=subject,
                task_type=item.get('type', 1),
            )

            images = item.get('image', [])
            for i, url in enumerate(images):
                if url:
                    TaskImage.objects.create(task=task, url=url, order=i)

            created += 1
        return created
