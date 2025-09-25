## Нарезчик видео

Простое приложение на Python (Tkinter) для нарезки видео на клипы фиксированной длины.

### Возможности
- Длина сегмента настраивается (по умолчанию 15 сек)
- Режим "Быстро (без перекодирования)" — копирование потоков (очень быстро, разрез по ключевым кадрам)
- Перекодирование H.264/AAC для совместимости
- Оценка прогресса, авто-открытие папки

### Зависимости
- Python 3.9+
- ffmpeg/ffprobe (ставится вне pip)
- Tkinter (входит в сборку Python; на macOS нужен Python с поддержкой Tk)

### Установка (macOS/Linux)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Установите ffmpeg: `brew install ffmpeg` (macOS), `sudo apt install ffmpeg` (Linux).

### Запуск
```bash
python app.py
```

### Сборка .exe для Windows (PyInstaller)
1) На Windows установите Python 3.12+ (желательно с `python.org`).
2) Установите зависимости:
```bat
pip install -r requirements.txt
```
3) Соберите exe:
```bat
build-windows.bat
```
После сборки готовый файл: `dist\video_slicer.exe`.

#### Бандлинг ffmpeg в exe (опционально)
По умолчанию приложение ищет `ffmpeg`/`ffprobe` в тех местах:
- Внутри PyInstaller-папки (если вы добавили бинарники как ресурсы)
- Рядом с `video_slicer.exe`
- В `PATH`

Чтобы положить `ffmpeg.exe` и `ffprobe.exe` внутрь exe-папки:
- Скопируйте их в `bin/` и добавьте в команду сборки флаги PyInstaller:
```bat
--add-binary "bin/ffmpeg.exe;." --add-binary "bin/ffprobe.exe;."
```
Или отредактируйте `build-windows.bat` и раскомментируйте соответствующие строки.

#### Примечания
- В режиме "быстро" возможны разрезы не точно по секундам (из-за ключевых кадров). Для точной длины — отключите быстрый режим (будет перекодирование).
- Для очень больших файлов быстрый режим рекомендуется.

### CI: Сборка .exe через GitHub Actions

Шаги:
1) Создайте новый репозиторий на GitHub.
2) Локально инициализируйте git и запушьте проект:
```bash
git init
git add .
git commit -m "init: video slicer"
git branch -M main
git remote add origin <ВАШ_REPO_URL>
git push -u origin main
```
3) В репозитории уже есть workflow `.github/workflows/windows-build.yml` — он соберёт `.exe` на Windows-раннере при каждом пуше в `main` и при создании тега `v*`.
4) После пуша откройте вкладку Actions — дождитесь завершения job `build-windows`.
5) Заберите артефакт `video_slicer-windows` или создайте релиз, пушнув тег:
```bash
git tag v1.0.0
git push origin v1.0.0
```
После тега workflow опубликует релиз с `video_slicer.exe` в разделе Releases.

Примечания:
- Workflow автоматически скачивает статические `ffmpeg.exe` и `ffprobe.exe` и вкладывает их в exe.
- Если URL ffmpeg станет недоступен, обновите ссылку в `.github/workflows/windows-build.yml` в шаге "Prepare ffmpeg (static)".
