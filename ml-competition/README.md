# 머신러닝 경진대회 플랫폼 (GitHub Pages + GitHub Actions)

캐글(Kaggle)과 비슷한 수업용 예측 경진대회를 **서버 없이** GitHub 저장소 하나로 운영하기 위한 템플릿입니다.

- **사이트**: GitHub Pages 에 올라가는 정적 페이지 (대회 목록·설명·데이터 다운로드·리더보드·제출 기록)
- **채점**: 학생이 제출 이슈를 열면 GitHub Actions 가 자동 채점하고, 이슈에 점수 댓글을 단 뒤 리더보드를 갱신·재배포
- **정답 보호**: 정답 파일은 암호화(`solution.csv.enc`)되어 저장소에 있고, 키는 Actions Secret 에만 존재
- **지원 기능**: Public/Private 리더보드 분리, 하루 제출 횟수 제한, 팀 단위 집계, 대회 여러 개 동시 운영, 중복 제출 파일 감지, 마감 후 최종 결과 공개, 교수자용 성적 파일(암호화) 생성

---

## 1. 동작 원리

```
학생 ─(제출 이슈: 대회 선택 + CSV 첨부)─▶ GitHub 저장소
                                            │  issues: opened  → .github/workflows/score.yml
                                            ▼
                               GitHub Actions (ubuntu 러너, 약 1~2분)
                                 1) 참가자 명단·기간·일일 한도 확인
                                 2) 첨부 CSV 다운로드 → 형식 검증
                                 3) solution.csv.enc 복호화 → Public/Private 점수 계산
                                 4) competitions/<대회>/leaderboard.json 갱신·커밋
                                 5) 이슈에 점수 댓글, 라벨(scored/rejected), 이슈 닫기
                                 6) 사이트(_site) 조립 → GitHub Pages 배포
                                            │
학생·교수자 ◀─────────────────── https://<계정>.github.io/<저장소>/
```

- Public 점수는 즉시 공개되고, **Private 점수는 암호화된 채로 저장**되어 마감 후 교수자가 `Finalize` 워크플로를 실행할 때 비로소 계산·공개됩니다.
- 학생의 신분은 **GitHub 계정**입니다. 교수자가 관리하는 참가자 명단(`participants.csv`)에서 GitHub 아이디 → 학번·이름·팀으로 연결합니다. 명단에 없는 계정의 제출은 자동 거부됩니다.
- 제출 방식은 두 가지를 지원합니다. **이슈 첨부 방식**(기본, 가장 쉬움)과 **Pull Request 방식**(비공개 저장소이거나 첨부 다운로드가 막혔을 때의 대안).

---

## 2. 준비물

- GitHub 계정 (교수자). 학생도 각자 GitHub 계정이 필요합니다.
- 로컬 PC 에 Python 3.11 이상과 git. (대회 생성·암호화는 로컬에서 한 번 실행하면 됩니다)

```bash
pip install -r scorer/requirements.txt
```

---

## 3. 빠른 시작 (처음 한 번, 약 30분)

### 3-1. 저장소 만들기

1. GitHub 에서 새 저장소를 만듭니다 (예: `ml-competition-2026`). **Public** 을 권장합니다 (Public 저장소는 Actions 실행 시간이 무제한, Pages 무료).
2. 이 폴더의 내용을 그대로 올립니다.
   ```bash
   cd ml-competition
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<계정>/<저장소>.git
   git push -u origin main
   ```
   `.gitignore` 에 의해 암호화 키(`.competition.key`), 평문 정답(`competitions/*/solution.csv`), 평문 명단(`participants.csv`), 데모 원본(`examples/`)은 올라가지 않습니다. 푸시 전에 `git status` 로 확인하세요.

### 3-2. 저장소 설정 (웹에서 클릭 4곳)

| 위치 | 설정 |
|---|---|
| Settings → Pages → **Build and deployment → Source** | **GitHub Actions** 선택 |
| Settings → Actions → General → **Workflow permissions** | **Read and write permissions** 선택 후 Save |
| Settings → Secrets and variables → Actions → **Secrets** → New repository secret | 이름 `COMPETITION_KEY`, 값은 아래 3-3 의 키 |
| Settings → Secrets and variables → Actions → **Variables** → New repository variable (선택) | 이름 `SITE_URL`, 값 `https://<계정>.github.io/<저장소>/` — 점수 댓글에 리더보드 링크를 넣을 때 사용 |

### 3-3. 암호화 키

배포본에는 데모 대회용 키(`.competition.key`)가 이미 들어 있습니다. 그대로 써도 되지만, 이 폴더를 다른 사람과 공유했다면 새로 만드십시오.

```bash
python -m scorer.crypto_tool show            # 현재 키 보기 → 이 값을 Secret COMPETITION_KEY 에 등록
# 새 키로 바꾸려면 (기존 .enc 파일과 저장된 Private 점수는 모두 다시 암호화해야 하므로 대회 생성 전에만 바꾸세요)
python -m scorer.crypto_tool keygen --force
```

### 3-4. 참가자 명단

학생들의 GitHub 아이디를 미리 수집합니다 (구글 폼으로 "학번, 이름, GitHub 아이디, 팀명" 을 받는 방식을 권장). `participants.csv.example` 을 참고해 `participants.csv` 를 만듭니다.

```csv
github,student_id,name,display_name,team
hong-gildong,20231234,홍길동,길동,
kim-ds,20231235,김데이터,,Alpha
lee-ml,20231236,이머신,,Alpha
```

- `github` 만 필수. `display_name` 은 리더보드 표시명(비우면 `name`, 그것도 없으면 GitHub 아이디). `team` 이 같은 학생들은 한 팀으로 집계됩니다.
- **공개 저장소라면 명단을 암호화해서 올리십시오.** 학번·이름이 공개되지 않습니다.
  ```bash
  python -m scorer.crypto_tool encrypt participants.csv     # → participants.csv.enc (이것만 커밋)
  ```
  평문 `participants.csv` 가 저장소에 있으면 그것이 우선 사용됩니다(비공개 저장소라면 평문도 무방).
- 명단을 고친 뒤에는 다시 암호화해서 커밋·푸시하면 다음 제출부터 반영됩니다.

### 3-5. 사이트 확인과 시험 제출

1. 푸시가 끝나면 Actions 탭에 "사이트 배포" 워크플로가 실행되고, 1~2분 뒤 `https://<계정>.github.io/<저장소>/` 에서 데모 대회 두 개가 보입니다.
2. `.github/ISSUE_TEMPLATE/config.yml` 의 `OWNER`, `REPO` 를 실제 값으로 바꿔 두면 이슈 작성 화면에 사이트 링크가 함께 표시됩니다.
3. 본인 GitHub 아이디를 명단에 넣은 뒤, 저장소 Issues → New issue → "📤 제출" 양식으로 `competitions/demo-house-price/data/sample_submission.csv` 를 제출해 봅니다. 1~3분 뒤 이슈에 점수 댓글이 달리고 리더보드에 나타나면 성공입니다.
4. 시험이 끝나면 리더보드를 비웁니다: `python -m scorer.local_test reset --competition demo-house-price` 실행 후 커밋·푸시. (데모 대회 자체를 지우려면 `competitions/demo-*` 와 `submissions/demo-*` 폴더를 삭제하고 `python -m scorer.new_competition ...` 으로 실제 대회를 만들 때 이슈 템플릿이 자동 갱신됩니다.)

---

## 4. 대회 만들기

### 4-1. 데이터 준비

캐글과 같은 구성입니다.

| 파일 | 내용 | 공개 여부 |
|---|---|---|
| `train.csv` | 입력 변수 + 정답 | 공개 |
| `test.csv` | 입력 변수만 (정답 열 제거!) | 공개 |
| `sample_submission.csv` | `id, target` 두 열, 제출 형식 예시 | 공개 |
| `solution.csv` | `id, target[, Usage]` — 테스트 데이터의 정답 | **비공개(암호화)** |

- `Usage` 열에 `Public` / `Private` / `Ignored` 를 직접 지정할 수 있습니다. 없으면 생성 시 `--public-ratio` 비율로 무작위 분할합니다 (분류 지표는 클래스별 층화 분할).
- id 는 고유해야 하고, 제출 파일의 id 집합이 solution 과 정확히 같아야 채점됩니다.

### 4-2. 생성 명령

```bash
python -m scorer.new_competition \
  --slug house-price --title "주택 가격 예측" --subtitle "한 줄 설명" \
  --metric rmse --id-column id --target-column price \
  --solution ./raw/solution.csv \
  --data ./raw/train.csv ./raw/test.csv \
  --sample ./raw/sample_submission.csv \
  --public-ratio 0.3 \
  --start 2026-11-20T00:00:00+09:00 --deadline 2026-12-14T23:59:59+09:00 \
  --daily-limit 5 --max-final 2
```

실행하면 `competitions/house-price/` 에 설정·설명·데이터·암호화 정답·빈 리더보드가 만들어지고, `submissions/house-price/` 폴더와 이슈 템플릿의 대회 선택 목록이 갱신됩니다. 이어서

1. `competitions/house-price/README.md` 를 열어 대회 설명(배경, 변수 설명, 규칙)을 작성하고
2. `git add -A && git commit -m "add house-price" && git push`

하면 1~2분 뒤 사이트에 대회가 나타납니다.

### 4-3. 평가지표 (`--metric`)

| 값 | 지표 | 제출값 | 방향 |
|---|---|---|---|
| `rmse` | Root Mean Squared Error | 실수 | 낮을수록 좋음 |
| `mae` | Mean Absolute Error | 실수 | 낮을수록 |
| `rmsle` | Root Mean Squared Log Error (음수 불가) | 실수 | 낮을수록 |
| `mape` | Mean Absolute Percentage Error (%) | 실수 | 낮을수록 |
| `r2` | 결정계수 | 실수 | 높을수록 |
| `accuracy` | 정확도 | 클래스 라벨 | 높을수록 |
| `f1` | 이진 F1 (양성 라벨은 `pos_label`, 기본 1) | 클래스 라벨 | 높을수록 |
| `f1_macro` | 다중 클래스 macro F1 | 클래스 라벨 | 높을수록 |
| `auc` | ROC AUC (정답은 0/1) | 확률 또는 점수 | 높을수록 |
| `logloss` | 이진 로그 손실 (정답은 0/1) | 0~1 확률 | 낮을수록 |

계산은 numpy 로 구현되어 있으며 scikit-learn 결과와 일치합니다. 다른 지표가 필요하면 `scorer/metrics.py` 의 `METRICS` 와 `compute()` 에 추가하면 됩니다.

### 4-4. `config.yml` 항목

| 항목 | 의미 | 기본값 |
|---|---|---|
| `title`, `subtitle` | 사이트에 표시되는 제목·한 줄 설명 | |
| `metric`, `id_column`, `target_column`, `pos_label` | 채점 기준 | |
| `start`, `deadline` | 제출 가능 기간 (ISO 8601, `+09:00` 권장). 이슈 **생성 시각** 기준으로 판정하므로 채점이 밀려도 공정 | 없음(무제한) |
| `timezone` | 일일 한도의 "하루" 기준 | `Asia/Seoul` |
| `daily_limit` | 참가 단위(팀이면 팀 전체)별 하루 제출 횟수. 0 이면 무제한. 실패한 제출은 세지 않음 | 5 |
| `max_final_submissions` | 최종 평가에 쓸 제출물 수(Public 상위 N개 중 Private 최고) | 2 |
| `teams` | `true` 면 명단의 `team` 열로 묶어 집계 | true |
| `score_decimals` | 표시 소수 자릿수 (리더보드 탐색 방지용으로 줄일 수 있음) | 5 |
| `max_file_mb` | 제출 파일 크기 제한 | 20 |
| `allow_unregistered` | 명단에 없는 계정도 허용 | false |
| `published` | `false` 면 사이트·이슈 템플릿에서 숨김 (준비 중 대회) | true |

수정 후 커밋·푸시하면 사이트가 재배포됩니다. 마감 연장은 `deadline` 만 고치면 됩니다.

---

## 5. 운영 중

### 어디를 보면 되나
- **Issues 탭**: 제출 하나가 이슈 하나. 라벨 `scored`(채점 완료) / `rejected`(형식 오류·한도 초과·명단 없음 등, 사유가 댓글에 있음) / `duplicate`(다른 참가자 파일과 동일) / `error`(시스템 오류, 교수자 확인 필요). 라벨로 필터링해 보십시오.
- **Actions 탭**: 워크플로 실행 기록. 실패(빨간색)가 있으면 로그를 열어 확인합니다.
- **사이트 → 제출 기록 탭**: 모든 채점된 제출과 메모, 중복 표시.

### 자주 하는 작업
- **학생 추가·팀 변경**: `participants.csv` 수정 → 암호화 → 커밋·푸시. 이미 들어온 제출의 팀 소속은 바뀌지 않으므로(제출 시점 기준 기록) 팀 확정은 가급적 대회 초반에 끝내십시오. 꼭 소급해야 하면 `leaderboard.json` 의 해당 제출 `participant_key`/`display`/`members` 를 직접 수정합니다.
- **재채점**: Actions 탭에서 해당 실행을 열어 **Re-run all jobs**. 같은 이슈 번호의 기록을 교체하므로 중복 기록이 생기지 않습니다. 정답 파일이 바뀐 경우 모든 이슈를 재실행해야 합니다.
- **제출 삭제(부정 등)·목록 확인**: 로컬에서 `git pull` 후
  ```bash
  python -m scorer.admin list   --competition house-price          # 제출 번호·참가자·점수 목록
  python -m scorer.admin remove --competition house-price --id 12  # 12번 제출 삭제 + 리더보드 재계산
  python -m scorer.admin private --competition house-price         # Private 순위 미리보기 (교수자 화면에만 출력)
  ```
  삭제 후 커밋·푸시하면 "사이트 배포" 워크플로가 자동 실행되어 반영됩니다.
- **최종 평가 제출물 수동 지정**: 학생이 특정 제출을 최종으로 쓰고 싶다고 요청하면 `competitions/<대회>/selections.yml` 에 적습니다.
  ```yaml
  "team:Alpha": [12, 15]
  "user:hong-gildong": [7]
  ```
  지정이 없는 참가자는 Public 상위 N개가 자동 선택됩니다.
- **마감 연장**: `config.yml` 의 `deadline` 수정 → 푸시.
- **대회 숨기기/공개**: `published: false/true`.

### 알아 둘 점
- 채점은 순차 처리(동시 실행 1개)입니다. 마감 직전 수십 명이 몰리면 결과 댓글이 수십 분 늦어질 수 있지만, 마감 판정은 **이슈 생성 시각** 기준이므로 불이익은 없습니다. 학생들에게 미리 알려 주십시오.
- 봇의 커밋은 `competition-bot` 이름으로 `leaderboard.json` 만 바꿉니다. 교수자가 같은 파일을 로컬에서 고칠 때는 먼저 `git pull` 하십시오.
- 공개 저장소에서는 이슈에 첨부된 제출 CSV 를 누구나 내려받을 수 있습니다. 다른 사람 파일을 그대로 내면 `duplicate` 라벨과 리더보드 표시가 남습니다(단, `sample_submission.csv` 와 같은 파일은 예외). 최종 성적에 코드·보고서 평가를 함께 두는 것을 권장합니다.

---

## 6. 마감 후: 최종 결과 공개

1. Actions 탭 → **최종 결과 공개 (Finalize)** → Run workflow → 대회 슬러그 입력 → Run.
2. 1~2분 뒤 사이트 리더보드에 **Private (최종)** 탭이 열리고 순위 변동(▲▼)이 표시됩니다. 대회 카드에는 "최종 결과 공개" 배지가 붙습니다.
3. 교수자용 성적 파일은 `competitions/<대회>/final_results.csv.enc` 로 커밋됩니다. 로컬에서 복호화하십시오.
   ```bash
   git pull
   python -m scorer.crypto_tool decrypt competitions/<대회>/final_results.csv.enc
   # → competitions/<대회>/final_results.csv (학번·이름·팀·Private/Public 점수·순위, 팀은 구성원별 행)
   ```
   이 평문 파일은 `.gitignore` 에 있어 커밋되지 않습니다.
4. 공개를 취소하려면 같은 워크플로에서 `unfinalize` 를 체크하고 실행합니다.

---

## 7. 문제 해결

| 증상 | 원인·조치 |
|---|---|
| 이슈를 열었는데 아무 댓글도 없음 | Actions 탭에서 실행 여부 확인. 실행 자체가 없으면 이슈에 `submission` 라벨이 없는 경우(양식을 쓰지 않고 빈 이슈를 만든 경우)입니다. 실행이 실패했다면 로그 확인 — 대부분 `COMPETITION_KEY` 미등록이나 Workflow permissions 미설정 |
| 댓글: "첨부파일을 내려받지 못했습니다" | GitHub 가 첨부파일 익명 다운로드를 막은 경우입니다. `site.yml` 의 `submission_mode` 를 `pr` 또는 `both` 로 바꾸고 학생들에게 PR 방식을 안내하십시오. PR 방식은 저장소 공개 여부와 무관하게 동작합니다 |
| 댓글: "참가자 명단에 없습니다" | 학생이 알려 준 아이디 오타가 대부분입니다. 이슈 작성자 아이디(이슈 상단 표시)를 명단에 넣고 다시 제출하게 하십시오 |
| 댓글: "복호화 실패" | Secret 의 키가 `.enc` 파일을 만들 때 쓴 키와 다릅니다. `python -m scorer.crypto_tool show` 값으로 Secret 을 갱신하십시오 |
| 사이트가 갱신되지 않음 | Settings → Pages 의 Source 가 **GitHub Actions** 인지 확인. 브라우저 캐시는 30초 단위로 무효화됩니다 |
| 리더보드 커밋 충돌 (push rejected) | 워크플로가 3회 재시도합니다. 반복되면 Actions 탭에서 해당 실행을 Re-run |
| 키를 잃어버림 | `.enc` 파일과 저장된 Private 점수는 복구할 수 없습니다. 키를 비밀번호 관리자 등 안전한 곳에 보관하십시오 |

### 비공개 저장소로 운영하려면
- GitHub Pro(교수자는 GitHub Education 으로 무료 신청 가능) 이상에서 비공개 저장소의 Pages 가 가능합니다. 학생들을 저장소 협력자(Read)로 초대해야 이슈·PR 을 열 수 있습니다.
- 비공개 저장소에서는 이슈 첨부파일을 Actions 가 내려받을 수 없으므로 **PR 방식**(`submission_mode: pr`)을 사용하십시오.
- 비공개 저장소의 Actions 는 월 2,000분 무료(Free/Pro)입니다. 제출 1회 ≈ 1분이므로 한 학기 수업 규모에서는 충분합니다.

---

## 8. 로컬 테스트

GitHub 없이 채점 로직을 확인할 수 있습니다 (명단 `participants.csv` 가 로컬에 있어야 합니다).

```bash
# 가짜 제출 → 댓글 내용이 화면에 출력되고 leaderboard.json 이 갱신됨
python -m scorer.local_test submit --competition demo-house-price \
    --file competitions/demo-house-price/data/sample_submission.csv --login hong-gildong \
    --created-at 2026-11-20T10:00:00+09:00

# 최종 결과 계산 (평문 성적 파일도 함께 저장)
python -m scorer.finalize --competition demo-house-price --plain-results

# 사이트 조립 후 브라우저에서 확인
python -m scorer.build_site --out _site && (cd _site && python -m http.server 8000)

# 시험 기록 삭제
python -m scorer.local_test reset --competition demo-house-price
```

---

## 9. 폴더 구조

```
.github/
  ISSUE_TEMPLATE/submission.yml   제출 양식 (대회 목록은 new_competition 이 자동 갱신)
  ISSUE_TEMPLATE/question.yml     질문 양식
  workflows/score.yml             제출 채점 (issues opened / pull_request_target)
  workflows/deploy-site.yml       교수자 푸시 시 사이트 재배포
  workflows/finalize.yml          최종 결과 공개 (수동 실행)
competitions/<slug>/
  config.yml                      대회 설정
  README.md                       대회 설명 (사이트 개요 탭)
  data/                           공개 데이터 (train, test, sample_submission)
  solution.csv.enc                암호화된 정답   (solution.csv 평문은 로컬 전용)
  leaderboard.json                제출 기록 + Public 리더보드 (봇이 갱신)
  private_leaderboard.json        최종 결과 (finalize 후)
  final_results.csv.enc           교수자용 성적 (finalize 후, 암호화)
  selections.yml                  (선택) 최종 평가 제출물 수동 지정
submissions/<slug>/               PR 방식 제출 폴더
scorer/                           채점·도구 코드 (Python)
site/                             정적 사이트 원본 (index.html, competition.html, assets/)
site.yml                          사이트 제목·설명·제출 방식
participants.csv(.enc)            참가자 명단 (github, student_id, name, display_name, team)
.competition.key                  암호화 키 (커밋 금지, Secret 과 동일 값)
examples/                         데모 합성 데이터 원본 (커밋 금지)
docs/STUDENT_GUIDE.md             학생 배포용 안내문
docs/KAGGLE_COMMUNITY.md          캐글 Community Competition 으로 운영할 때의 절차 비교
```

---

## 10. 보안·개인정보 메모

- 정답은 Fernet(AES-128-CBC + HMAC) 대칭키로 암호화됩니다. 키는 Secret 과 로컬 `.competition.key` 두 곳에만 둡니다.
- 참가자 명단을 암호화하면 저장소에 학번·이름이 평문으로 남지 않습니다. `leaderboard.json` 에는 표시명과 GitHub 아이디만 기록됩니다(아이디는 어차피 이슈 작성자로 노출됩니다).
- PR 방식에서도 학생 코드가 실행되는 일은 없습니다. 워크플로는 항상 기본 브랜치의 채점 코드만 실행하고, PR 에서는 CSV 파일 내용만 읽습니다.
- `final_results.csv.enc` 외에 성적을 평문으로 커밋하지 마십시오.
