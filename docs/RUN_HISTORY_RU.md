# История приёмки

Все указанные исполнения — GitHub-hosted Actions. Неуспешные попытки сохранены.

| Run | Содержание | Итог |
|---|---|---|
| [36228034033](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36228034033) | Фиксация окружения, Mk01 и JSON-заголовка | PASS |
| [36228702414](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36228702414) | E0 самостоятельного GRID, DES/DAG/SimPy | PASS; не приёмка исходного TSFG |
| [36229284418](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36229284418) | Первое подключение закрытого S1 | FAIL: SSH-аутентификация; моделирование не началось |
| [36229821826](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36229821826) | Исправлен формат существующего ключа; 157 тестов S1 и E0 с адаптером | PASS |
| [36230125852](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36230125852) | Первая полная серия Mk01 | PASS |
| [36230395401](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36230395401) | Окончательная приёмка с проверкой JSON-контрактов | PASS; источник опубликованного архива |

Основной исполняемый код приёмки: commit
`75776d6c81806fdd2a53c8faf95e8283ef2409f6`. Позднейшие изменения публикации добавляют
документацию и точные копии артефактов; они не подменяют результаты новым запуском.

Код исходного S1 не менялся. Публичный адаптер, исходное ядро и собранный бинарник
идентифицированы в `docs/results/mk01/tsfg-provenance.json`. Архив включает
полные входы и результаты; частный исходник и его Go-бинарник исключены.
