# AISoundFix

## 로컬 스튜디오

오디오 API와 웹 화면을 같은 프로세스에서 실행한다. 프로젝트 루트에서 Python 환경을 활성화하고 FFmpeg와 FFprobe를 PATH에 둔 뒤 실행한다.

```powershell
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 4001
```

이 작업 공간에 설치된 휴대용 Python과 FFmpeg를 사용하려면 다음 명령으로 시작한다.

```powershell
$env:PATH = (Resolve-Path .venv/ffmpeg).Path + ';' + $env:PATH
.\.venv\tools\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 4001
```

메인 플레이어의 ‘음색 미리듣기’에서 양자화, 풍성함, 입체감을 조합하고 A/B로 원본과 비교한다. 기본 샘플은 `data/sound`에서 파일 이름순으로 첫 번째 곡이다. ‘음원 불러오기’로 자신의 곡도 같은 플레이어에서 비교할 수 있다. ‘전체 곡에 적용’ 또는 ‘이 구간에만 적용’을 선택하면 해당 설정으로 WAV를 저장할 수 있다. [로컬 스튜디오](http://127.0.0.1:4001/)

파형에서 구간을 선택하고 ‘ㅅ 소리가 튀어요’ 또는 ‘소리가 먹먹해요’에서 보정을 미리 듣는다. 적용한 뒤 저장하면 해당 구간이 보정된 전체 곡 WAV를 받는다. 보컬과 반주 WAV가 있으면 스템 화면에서 두 파일을 함께 불러올 수 있다. [DSP·양자화 실험](docs/decisions.md#suno-구간-편집과-24비트-저장-실험)
