# Архитектура Vokal Director

## Зачем такой подход

`Vokal Director` не должен быть очередным генератором песен. Главная ценность продукта:

- разобрать уже существующую песню;
- понять ее структуру, партии и проблемные места;
- адаптировать материал под реальную группу, ученика или ансамбль;
- выдать рабочий `Stage Pack`: партии, аккорды, MIDI, stems, минус, клик, репетиционные треки и версии аранжировки.

Поэтому архитектура строится как оркестратор специализированных моделей и сервисов. Мы берем готовые модели там, где рынок уже силен, а свое делаем там, где возникает продуктовая дифференциация: `SongGraph`, правила аранжировки, педагогическая адаптация, версии, проверка, выдача материалов и AI-директор.

## Архитектурные принципы

- `SongGraph` является центральной внутренней моделью песни.
- Все внешние AI/audio-провайдеры подключаются через адаптеры, а не напрямую из экранов.
- Любой автоматический результат считается проверяемым черновиком.
- Сначала моки повторяют будущие доменные сущности, затем моки заменяются реальными сервисами.
- В интерфейсе не обещаем идеальную автоматическую нотную запись.
- Пользовательские файлы хранятся приватно, с удалением исходников и результатов.
- Авторские материалы не превращаются в публичный каталог нот.
- Дорогие операции считаются как jobs с оценкой сложности и стоимости.

## Текущий инкремент

Первый инкремент: русскоязычный frontend-мок на `Vite + React + TypeScript`.

Что реально работает:

- сценарии `Для группы` и `Для обучения`;
- выбор цели обработки;
- загрузочный flow без реальной отправки файла;
- демо-проекты;
- моковая обработка по шагам;
- рабочий экран `Stage Pack`;
- версии аранжировки;
- сомнительные такты и статусы проверки;
- моковые AI-действия;
- моковая раздача материалов;
- согласие и приватный режим;
- оценка сложности обработки.

Что пока не работает реально:

- разделение аудио на stems;
- транскрипция в MIDI/MusicXML/PDF;
- распознавание аккордов из аудио;
- генерация настоящих PDF/MIDI/audio-файлов;
- backend API;
- хранение файлов;
- авторизация;
- платежи;
- реальные AI-вызовы;
- реальные ссылки общего доступа.

## Целевая схема

```text
Web App
  |
  | REST/Realtime API
  v
API Gateway
  |
  +-- Project Service
  +-- Upload Service
  +-- Processing Service
  +-- Stage Pack Service
  +-- Director Service
  +-- Review Service
  +-- Version Service
  +-- Sharing Service
  +-- Billing/Quota Service
  +-- Legal/Retention Service
  |
  v
Job Queue
  |
  +-- Audio Worker
  +-- Analysis Worker
  +-- Transcription Worker
  +-- Notation Worker
  +-- Director Worker
  +-- Export Worker
  |
  v
Storage
  +-- Postgres: проекты, версии, статусы, права, история
  +-- Object Storage: исходники, stems, MIDI, PDF, ZIP
  +-- Redis/Queue: jobs, прогресс, retry
  +-- Logs/Analytics: события продукта и качество результата
```

## Frontend

### Первый прототип

Используем:

- Vite;
- React;
- TypeScript;
- Vitest;
- lucide-react;
- обычный CSS с токенами, без тяжелой дизайн-системы.

Почему так:

- репозиторий пока документационный и пустой с точки зрения приложения;
- нам нужен быстрый кликабельный продуктовый мок;
- TypeScript сразу фиксирует доменную модель;
- Vite проще для первого рабочего прототипа, чем полноценный Next.js.

### Будущее развитие

Позже можно остаться на Vite, если это будет SPA/workspace, или перейти на Next.js, если понадобятся:

- server-side rendering;
- личные кабинеты;
- публичные страницы;
- документация;
- платежные страницы;
- SEO для маркетинговых страниц.

UI-компоненты должны быть отделены от сервисов:

- компоненты получают `Project`, `StagePack`, `DirectorSuggestion`, `ReviewIssue`;
- компоненты не знают, был ли результат получен из мока, AudioShake, Klangio или нашего backend;
- все операции идут через сервисные интерфейсы.

## Backend

### API Gateway

Отвечает за:

- авторизацию;
- проверку прав доступа;
- маршрутизацию запросов;
- rate limits;
- выдачу signed upload/download URL;
- создание jobs;
- realtime-обновления прогресса.

Возможный стек:

- NestJS, если хотим весь backend на TypeScript;
- FastAPI, если audio/ML-команда будет жить ближе к Python;
- Postgres;
- Redis или managed queue;
- S3/R2-compatible object storage.

Решение для V1 backend: начать с NestJS или FastAPI после мокового продукта. Если команда маленькая и audio/ML код в Python, FastAPI будет проще. Если хотим единую TypeScript-команду и строгие контракты с frontend, NestJS будет удобнее.

### Основные API

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/:projectId
PATCH  /api/projects/:projectId

POST   /api/uploads/presign
POST   /api/projects/:projectId/uploads/complete

POST   /api/projects/:projectId/processing-jobs
GET    /api/processing-jobs/:jobId
POST   /api/processing-jobs/:jobId/retry

GET    /api/projects/:projectId/stage-pack
GET    /api/projects/:projectId/artifacts/:artifactId

POST   /api/projects/:projectId/director/actions
POST   /api/projects/:projectId/director/chat

POST   /api/projects/:projectId/versions
PATCH  /api/projects/:projectId/versions/:versionId/select
POST   /api/projects/:projectId/versions/:versionId/rollback

PATCH  /api/projects/:projectId/review-issues/:issueId
POST   /api/projects/:projectId/review-comments

POST   /api/projects/:projectId/share-links
POST   /api/projects/:projectId/export-bundles

POST   /api/projects/:projectId/delete-source
POST   /api/projects/:projectId/delete-results
```

## Доменные модели

### Project

Корневая сущность.

Хранит:

- название;
- сценарий: `band` или `education`;
- выбранную цель обработки;
- upload;
- текущую версию;
- анализ песни;
- Stage Pack;
- warnings;
- review issues;
- recipients;
- consent;
- cost estimate;
- историю изменений.

### SongGraph

Наша главная собственная модель.

`SongGraph` связывает:

- секции песни;
- такты;
- темп;
- размер;
- тональность;
- аккорды;
- события формы: повтор, coda, пауза, tempo change, смена размера;
- партии инструментов;
- вокальные диапазоны;
- confidence по секциям и партиям;
- ссылки на stems, MIDI, MusicXML и PDF;
- места, требующие проверки.

Почему делаем свое:

- внешние модели возвращают разные форматы;
- продукту нужна единая карта песни;
- версии аранжировки должны изменять не “файлы”, а музыкальную структуру;
- AI-директору нужен детерминированный объект, а не набор разрозненных PDF/MIDI.

### ArrangementVersion

Версия аранжировки:

- `Оригинал`;
- `Для группы`;
- `Easy`;
- `Original-like`;
- `Advanced`;
- `Концертная`;
- `Ансамблевая`;
- `После репетиции`;
- `После урока`.

Каждая версия хранит:

- родительскую версию;
- список изменений;
- какие артефакты актуальны;
- какие артефакты устарели;
- комментарии;
- автора действия;
- дату;
- статус проверки.

### StagePack

Пакет результата.

Содержит:

- общую партитуру;
- партии;
- TAB;
- chord chart;
- lyrics + chords;
- MIDI;
- stems;
- минус;
- клик;
- репетиционные треки;
- ZIP;
- версии для преподавателя, ученика, музыканта или всей группы.

### DirectorAction

Детерминированная команда, которую можно выполнить безопасно.

Примеры:

- `transpose_down_2`;
- `merge_guitars`;
- `move_strings_to_keys`;
- `simplify_drums`;
- `create_beginner_bass`;
- `boost_chorus`;
- `create_practice_track_without_bass`;
- `create_advanced_student_part`;
- `split_to_student_ensemble`;
- `prepare_lesson_analysis`.

LLM не должен напрямую править файлы. Он предлагает или выбирает `DirectorAction`, а выполнение идет через наши правила и workers.

### ReviewIssue

Проверяемое место.

Статусы:

- `нужно проверить`;
- `проверено`;
- `исправлено`;
- `сомнительно`;
- `принято для репетиции`.

### ShareRecipient и ShareLink

Получатель и моковая или реальная ссылка:

- музыкант;
- ученик;
- преподаватель;
- родитель;
- группа;
- ансамбль.

Важно: не всем выдаем один и тот же материал. У учителя может быть версия с заметками, у ученика только его партия и домашнее задание.

## AI/audio pipeline

### 1. Ingest

Вход:

- MP3;
- WAV;
- FLAC;
- M4A.

Задачи:

- проверить формат;
- проверить длительность;
- проверить права/согласие;
- сохранить исходник;
- извлечь технические метаданные;
- оценить качество исходника.

Готовое:

- ffmpeg на backend/worker;
- в browser-only режиме можно рассмотреть ffmpeg.wasm, но не для тяжелой обработки больших файлов.

Свое:

- правила приемки файла;
- понятные предупреждения пользователю;
- расчет сложности обработки.

### 2. Source separation

Задачи:

- vocals;
- lead vocal;
- backing vocals;
- drums;
- bass;
- guitar;
- piano/keys;
- strings;
- instrumental;
- other.

Готовое:

- AudioShake API для production-качества и разных stem-моделей;
- Demucs как open-source/self-host путь и fallback.

Свое:

- выбор модели под тариф, жанр, длительность и нужные stems;
- оценка качества stem;
- правила повторной обработки;
- mapping stems в `SongGraph`.

### 3. Beat, tempo, meter, structure

Задачи:

- BPM;
- downbeats;
- размер;
- темповые изменения;
- секции;
- повторы;
- coda/outro;
- паузы;
- медли.

Готовое:

- Klangio API заявляет beat tracking, BPM и meter;
- Essentia/librosa можно использовать как self-host analysis слой;
- часть структуры можно получить эвристиками по энергии, повторяемости и вокальным событиям.

Свое:

- `StructureDetector`, который объединяет сигналы нескольких моделей;
- confidence по секциям;
- UI для ручной правки формы.

### 4. Chord recognition

Задачи:

- аккордовая сетка;
- тайминги;
- тональность;
- спорные аккорды;
- варианты упрощения для школы.

Готовое:

- Klangio API заявляет chord recognition;
- Essentia полезна для анализа уже найденных последовательностей, но не закрывает весь продуктовый слой.

Свое:

- `ChordNormalizer`;
- правила enharmonic spelling;
- упрощение аккордов для ученика;
- Nashville/ступени позже;
- связь аккордов с тактами и секциями `SongGraph`.

### 5. Audio-to-MIDI transcription

Задачи:

- вокальная мелодия;
- бас;
- гитара;
- клавиши;
- основные drum events;
- MIDI по партиям.

Готовое:

- Basic Pitch для audio-to-MIDI, особенно на отдельных stems и одиночных инструментах;
- Klangio для инструментальной транскрипции в MIDI, MusicXML, PDF и GP5;
- специализированные модели можно тестировать отдельно по инструментам.

Свое:

- post-processing MIDI;
- quantization;
- исправление длительностей;
- удаление мусорных нот;
- разбиение по рукам/струнам;
- перенос партии под ограничения конкретного музыканта;
- confidence и review flags.

### 6. Lyrics and vocal alignment

Задачи:

- текст;
- line-level transcript;
- word-level timing;
- привязка текста к вокальной партии;
- подсказки дыхания;
- интервалы для ученика.

Готовое:

- AudioShake transcription/alignment для песен и тайм-синхронизации;
- speech-to-text модели можно использовать только как вспомогательный слой, потому что пение отличается от речи.

Свое:

- lyric cleanup;
- привязка строк к секциям;
- UI для ручной правки слов;
- вокальные подсказки и дыхание.

### 7. Notation and exports

Задачи:

- MusicXML;
- PDF;
- SVG preview;
- MIDI export;
- TAB;
- chord chart;
- lead sheet;
- A4 для печати;
- mobile/stage view.

Готовое:

- OpenSheetMusicDisplay для browser-preview MusicXML;
- Verovio для SVG/MIDI/MEI/MusicXML workflows;
- music21 для Python-based анализа, преобразований и генерации музыкальных структур;
- MuseScore CLI можно оценить для server-side PDF rendering.

Свое:

- шаблоны партий Vokal;
- крупный сценический вид;
- учебные разметки;
- правила экспорта для группы, ученика и преподавателя;
- проверяемые diff между версиями.

### 8. AI Director

Задачи:

- объяснить структуру песни;
- найти несоответствие между оригиналом и составом;
- предложить адаптации;
- превратить chat-команду в безопасное действие;
- создать версию;
- объяснить, что изменилось;
- предупредить, где нужна ручная проверка.

Готовое:

- LLM через адаптер, например OpenAI Responses API;
- для сложного reasoning можно использовать более сильную модель;
- для массовых коротких подсказок можно использовать более дешевую модель.

Рекомендуемая стартовая политика моделей:

- `gpt-5.6-terra` как баланс качества и стоимости для AI-директора;
- `gpt-5.6-sol` для сложных разборов, длинных SongGraph и спорных правок;
- более дешевый класс модели для коротких UI-пояснений, если качество достаточно.

Свое:

- `DirectorAction` DSL;
- rules engine;
- ограничения инструментов;
- педагогическая модель сложности;
- проверка допустимости действия;
- версионирование;
- audit trail.

Важно: LLM не делает музыкальную истину. Он объясняет, планирует и выбирает действия. Музыкальные изменения применяет наш deterministic слой.

### 9. Music generation

Это не ядро MVP.

Возможное будущее:

- генерация недостающего backing track;
- создание учебной фонограммы;
- вариации концовки;
- тренировочные loop-фрагменты.

Готовое:

- Lyria/Vertex AI или другие text-to-music модели можно рассматривать для генерации нового аудио, когда у пользователя есть права и задача не связана с копированием чужой записи.

Свое:

- для Vokal важнее не генерировать “новую песню”, а адаптировать и объяснять существующую;
- если правовой или качественный слой не закрывается готовыми моделями, делаем MIDI/synth-based practice renderer сами.

## Что точно делаем своим

### SongGraph

Свой канонический формат песни. Это основа продукта.

### Arrangement Engine

Правила:

- транспозиция;
- объединение партий;
- перенос струнных на клавиши;
- упрощение ритма;
- усложнение партии для сильного ученика;
- усиление припева;
- концертная концовка;
- ансамблевая раскладка.

### Pedagogy Engine

Учебная логика:

- уровень ученика;
- возраст;
- инструмент дома;
- чтение нот;
- знание аккордов;
- цель урока;
- домашнее задание;
- переход `Easy -> Original-like -> Advanced`.

Готового универсального продукта под эту задачу фактически нет, поэтому это сильная зона Vokal.

### Confidence and Review Engine

Слой честности:

- где модель уверена;
- где сомневается;
- что нужно проверить музыканту;
- что уже исправлено;
- что принято для репетиции.

### Version Engine

Не просто файлы, а музыкальные версии:

- родительская версия;
- diff;
- актуальность артефактов;
- откат;
- история AI-действий;
- история ручных правок.

### Export and Distribution Rules

Кому что выдавать:

- вся группа;
- конкретный музыкант;
- преподаватель;
- ученик;
- ансамбль;
- родитель.

## Что берем готовым, если качество устроит

| Зона | Первый выбор | Альтернатива | Если не хватает |
| --- | --- | --- | --- |
| Stems | AudioShake | Demucs self-host | свой router качества и повторной обработки |
| Open-source stems | Demucs | MDX/Spleeter для тестов | свой post-processing |
| Audio-to-MIDI | Basic Pitch для stems | Klangio | свой постпроцессинг и instrument adapters |
| Music transcription API | Klangio | отдельные модели по инструментам | свой pipeline вокруг MIDI/MusicXML |
| Lyrics alignment | AudioShake | STT как вспомогательно | свой lyric review UI |
| Beat/BPM/meter | Klangio | Essentia/librosa | свой StructureDetector |
| MusicXML preview | OpenSheetMusicDisplay | Verovio | свой stage/mobile view поверх MusicXML |
| PDF/MIDI export | Verovio, MuseScore CLI, music21 | собственный export worker | свои шаблоны и post-processing |
| AI reasoning | OpenAI Responses API | другой LLM-провайдер через адаптер | свой DirectorAction DSL и rules engine |
| Music generation | Lyria/Vertex AI позже | другие провайдеры | свой MIDI/synth practice renderer |

## Что может отсутствовать на рынке

Эти части не стоит ждать от готовых API:

- качественное “сделай песню удобной именно для моего состава”;
- разложить песню на школьный ансамбль с учетом уровня каждого ученика;
- сделать партию сложнее, если ученик сильнее оригинального учебного уровня;
- объяснить, почему припев теряет энергию в текущем составе;
- вести версии `После репетиции` и `После урока`;
- честно связать confidence, такты, партии и артефакты;
- выдавать разные материалы разным ролям;
- превращать “усиль припев” в проверяемую музыкальную операцию.

Это делаем своим продуктовым ядром.

## Processing lifecycle

```text
uploaded
  -> accepted
  -> normalized
  -> separated
  -> analyzed
  -> transcribed
  -> graph_built
  -> stage_pack_generated
  -> director_reviewed
  -> ready_for_review
  -> ready_for_distribution
```

Ошибки:

```text
failed_format
failed_upload
failed_separation
failed_transcription
low_confidence
needs_manual_review
distribution_stale
deleted
```

## Очереди и ретраи

Каждая тяжелая операция идет как job:

- idempotency key;
- входные artifact IDs;
- версия модели;
- стоимость;
- статус;
- progress;
- retry count;
- error code;
- выходные artifact IDs.

Нельзя просто перезаписать файлы. Нужно знать, какой model run создал какой artifact.

## Хранение

### Postgres

Хранит:

- users;
- projects;
- uploads;
- processing_jobs;
- arrangement_versions;
- song_graphs;
- artifacts;
- review_issues;
- review_comments;
- director_actions;
- share_recipients;
- share_links;
- export_bundles;
- legal_consents;
- deletion_requests;
- billing_events.

### Object Storage

Хранит:

- original audio;
- normalized audio;
- stems;
- previews;
- MIDI;
- MusicXML;
- PDF;
- ZIP;
- logs крупных model outputs, если можно хранить по privacy policy.

### Redis/Queue

Используется для:

- очередей обработки;
- realtime progress;
- locks;
- retry backoff;
- rate limits.

## Безопасность и права

Минимум для реального продукта:

- signed upload URLs;
- signed download URLs;
- вирус/format scan;
- лимит длительности и размера;
- private-by-default projects;
- удаление исходника;
- удаление результатов;
- разделение ролей;
- audit log;
- запрет публичного каталога чужих нот;
- хранение согласий;
- ограничения публичного распространения.

Юридические документы пишутся отдельно и не входят в моковый инкремент.

## Наблюдаемость и качество

Нужно измерять:

- сколько пользователей открыли демо;
- сколько дошли до `Stage Pack`;
- какие сценарии выбирают;
- какие цели обработки выбирают;
- какие артефакты открывают;
- какие AI-действия запускают;
- где отмечают ручные правки;
- какие жанры и исходники дают низкую точность;
- сколько стоит обработка по типам jobs;
- сколько раз перезапускают обработку.

Для ML-качества:

- confidence по stem;
- confidence по партии;
- confidence по секции;
- количество ручных исправлений;
- доля accepted review issues;
- сравнение провайдеров на одном benchmark-наборе.

## Модель выбора провайдера

Нужен `ModelRouter`.

Вход:

- цель обработки;
- жанр;
- длительность;
- качество исходника;
- нужные stems;
- нужные артефакты;
- тариф пользователя;
- срок;
- privacy constraints.

Выход:

- provider;
- model id;
- fallback provider;
- expected cost;
- expected runtime;
- quality risk;
- required review level.

Пример:

```json
{
  "task": "separate_stems",
  "provider": "audioshake",
  "models": ["vocals", "drums", "bass", "guitar", "keys"],
  "fallback": "demucs_htdemucs_6s",
  "expectedCostCredits": 5,
  "reviewLevel": "medium"
}
```

## Этапы внедрения

### Этап 1: Моковый продукт

- frontend;
- реальные доменные типы;
- моковые сервисы;
- демо-проекты;
- кликабельный `Stage Pack`;
- локальная сборка и GitHub.

### Этап 2: Реальные upload/jobs

- backend;
- object storage;
- jobs;
- progress;
- реальные artifact records;
- без настоящей AI-обработки или с одной простой операцией.

### Этап 3: Первое audio ядро

- нормализация;
- Demucs или AudioShake;
- stems;
- минус;
- репетиционные треки;
- качество и предупреждения.

### Этап 4: Первое MIDI/notation ядро

- Basic Pitch/Klangio;
- MIDI drafts;
- MusicXML drafts;
- OSMD preview;
- PDF export.

### Этап 5: Vokal Director ядро

- `SongGraph`;
- `DirectorAction`;
- Arrangement Engine;
- Review Engine;
- Version Engine;
- AI Director LLM adapter.

### Этап 6: Обучение и ансамбли

- Pedagogy Engine;
- ученик/класс/ансамбль;
- домашние задания;
- Easy/Original-like/Advanced;
- роли материалов.

### Этап 7: Оплата, лимиты, production

- billing;
- quotas;
- модель стоимости;
- privacy policy;
- retention;
- monitoring;
- provider benchmark.

## Открытые технические вопросы

Нужно проверить практическими тестами:

- качество stems на русскоязычных pop/rock песнях;
- качество гитарной транскрипции после stem separation;
- насколько Klangio подходит для плотного микса;
- где Basic Pitch дает мусорные ghost notes;
- что лучше для server-side PDF: MuseScore CLI, Verovio или music21 pipeline;
- сколько стоит обработка одной песни на AudioShake;
- какие provider terms разрешают учебные и репетиционные сценарии;
- какие ограничения нужны для школ и несовершеннолетних.

## Источники для выбора готовых моделей

- AudioShake Developer Docs: source separation, lyric transcription, alignment and model credit costs: https://developer.audioshake.ai/models
- Demucs official repository: Hybrid Transformer Demucs and open-source source separation: https://github.com/vvigot/demucs
- Spotify Basic Pitch: audio-to-MIDI transcription, model runtimes and supported formats: https://github.com/spotify/basic-pitch
- Klangio Transcription API: MIDI, MusicXML, PDF, GP5, source separation, beat tracking and chord recognition: https://api-docs.klang.io/
- OpenSheetMusicDisplay docs: browser MusicXML loading and rendering: https://opensheetmusicdisplay.github.io/classdoc/classes/OpenSheetMusicDisplay.html
- Verovio documentation: MusicXML/MEI/SVG/MIDI workflows: https://book.verovio.org/
- music21 documentation: Python toolkit for musicology, notation and analysis: https://music21.org/music21docs/
- OpenAI model docs: LLM model options and Responses API: https://platform.openai.com/docs/models
- Google DeepMind Lyria: music generation model family for possible future backing-track generation: https://deepmind.google/models/lyria/
