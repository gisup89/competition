# 대안: Kaggle Community Competition 으로 운영하기

GitHub 방식 대신(또는 병행하여) 캐글이 무료로 제공하는 **Community Competitions** 기능으로 같은 대회를 열 수 있습니다. 아래 내용은 캐글 공식 문서(https://www.kaggle.com/docs/competitions-setup, 2026-11 확인)를 기준으로 정리한 것입니다.

## 요약 비교

| 항목 | Kaggle Community Competition | 이 저장소 (GitHub Pages + Actions) |
|---|---|---|
| 비용·서버 | 무료, 서버 없음 | 무료, 서버 없음 |
| 학생 계정 | 캐글 계정 (전화번호 인증 필요할 수 있음) | GitHub 계정 |
| 채점 속도 | 즉시 (수 초) | 1~3분, 순차 처리 |
| 제출 비공개 | 제출 파일은 본인만 봄 | 공개 저장소면 첨부파일 공개 (중복 감지로 보완) |
| 로그인·팀·일일 한도·Public/Private | 모두 내장 | 모두 구현됨 (명단 파일로 관리) |
| 커스터마이징 | 제한적 (UI·규칙은 캐글 틀 안에서) | 코드·사이트 자유 수정 |
| 데이터 공개 범위 | Private + 링크 보유자/이메일 제한 가능 | 공개 저장소면 데이터 공개 |
| 참가자 이메일 | 다운로드 불가 (문서 명시) | 명단을 직접 관리 |
| 운영 중 변경 | 정답 파일 교체 후 전체 재채점은 캐글 지원팀 요청 필요 | 재실행으로 즉시 재채점 |
| 캐글 노트북 | 학생이 캐글 노트북에서 바로 작업 가능 | 해당 없음 |

## 캐글에서 만드는 절차 (공식 문서 기준)

1. **대회 생성**: 캐글 Community 랜딩 페이지에서 "Create new competition" → "Machine Learning Competition" 선택.
2. **공개 범위**: Visibility 는 `Public`(검색 노출) 또는 `Private`(초대 URL 로만 접근). Who can join 은 `Anyone` / `Only people with a link` / `Restricted email list`(특정 도메인·이메일만, 이때 노트북은 기본 비활성화) 중 선택. 수업용은 **Private + 링크 보유자** 또는 **이메일 제한(@hnu.kr 등)** 이 적합합니다.
3. **데이터 준비** (이 저장소와 동일한 구성):
   - `train.csv`(입력+정답), `test.csv`(입력만), `solution.csv`(정답), `sample_submission.csv`(형식)
   - 첫 열은 고유 **Id** 열이어야 하고, `solution.csv` 에는 **`Usage` 열**(`Public` / `Private` / `Ignored`)을 둡니다.
4. **채점 설정**: Host → Evaluation Metric 에서 지표 선택. 두 종류가 있습니다.
   - Legacy Metrics: 기존 지표, 열 매핑 수동 지정
   - Custom Python Metrics: 파이썬 노트북으로 작성하는 지표(공개 소스·문서 있음). 함수는 `solution, submission, row_id_column_name` 인자를 받아야 하고, 30분 실행 제한, 인터넷 불가.
   - `solution.csv` 와 `sample_submission.csv` 를 업로드하고 열을 매핑합니다. 공개 데이터는 Data 탭에서 업로드합니다.
5. **테스트**: Sandbox 에서 본인 제출로 채점을 확인(완벽한 제출이 만점이 나오는지). 특정 제출을 **Benchmark** 로 지정해 리더보드 기준선으로 보여 줄 수 있습니다.
6. **마무리·공개**: Basic Details 에서 이미지와 **표시 소수 자릿수(Score Decimals)** 를 설정(자릿수를 줄이면 리더보드 탐색 방지). Launch Checklist 가 모두 초록색이 되면 즉시 또는 예약 공개. 초대 URL 을 학생에게 공유합니다.

## 운영 시 알아 둘 점 (문서 FAQ)

- 정답 파일을 새로 올릴 수는 있으나, 진행 중 대회의 **전체 재채점은 캐글 지원팀에 요청**해야 합니다.
- 캐글은 Community Competition 에 대해 개별 지원을 제공하지 않으며, Competition Hosting 포럼에서 도움을 받습니다.
- 개인정보 보호를 위해 **참가자 이메일은 다운로드할 수 없습니다.** 성적 처리를 위해서는 학생이 캐글 표시명(또는 팀명)을 학번과 함께 알려 주도록 해야 합니다.
- 상금은 최대 25,000 USD 까지 걸 수 있으나(해당 없음) 지급은 호스트 책임입니다.

## 어떤 경우에 캐글이 더 나은가

- 학생들이 어차피 캐글 노트북(무료 GPU) 환경에서 과제를 수행하게 하려는 경우
- 제출 파일의 비공개성과 즉시 채점이 중요한 경우
- 리더보드 외에 토론(Discussion)·코드 공유 기능을 수업에 활용하려는 경우

반대로 사이트 문구·규칙·채점 로직을 직접 통제하고 싶거나, 학생들에게 GitHub 사용 경험을 함께 주고 싶거나, 캐글 계정 생성(전화 인증)이 부담스러운 경우에는 이 저장소 방식이 낫습니다. 두 방식은 같은 데이터 파일 구성을 쓰므로 데이터만 준비해 두면 어느 쪽으로든 열 수 있습니다.
