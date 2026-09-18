# D293 · 폰 앱 주행 모델 교체

차량을 켠 상태의 **P단·정차·주행 보조 비활성**에서 앱의 **기기 → 주행 모델**로 선택·다운로드한다. C4에서 폰 연결/변경 권한을 승인해야 한다. 주차 조건이 풀리거나 신호가 만료되면 다운로드와 저장을 보류하고 기존 모델을 유지한다. 다음에 조건을 만족하면 대기 요청을 다시 처리한다.

- sunnypilot 공식 카탈로그의 호환 모델만 선택한다. 카탈로그 내용이 바뀌면 다시 선택해야 한다.
- 임시 폴더로 다운로드하고 SHA-256 검증이 끝난 뒤 다음 기동 모델을 저장한다. 실패/취소/요청 교체는 기존 모델 파일을 보존한다.
- 기본 CD210 복귀는 진행 중인 요청도 취소한다. 모델 변경은 현재 추론 프로세스를 재시작하지 않는다.
- **현재 실행**, **다음 기동**, **요청/진행/실패**를 구분한다. 다음 기동의 실제 추론 출력에서 모델 ref와 artifact 서명을 확인해야 실행 확인으로 표시한다.
- 집 수신은 읽기 전용이다. 폰 변경 권한 만료와 C4의 새 승인을 유지한다.
- v0.21 앱에서 구형 C4 서버는 ‘C4 모델 관리 업데이트 필요’로 표시한다.

## 검증 범위

| 검사 | 결과 |
|---|---|
| PC 폰 HTTPS/권한/상태 회귀 | 124 통과 |
| PC 도로 입력 회귀 | 217 통과 |
| Android JVM | 66 통과 |
| APK assemble/lint | 통과 |
| Android 에뮬레이터 모델 UI | 13 확인 |
| C4 별도 폴더 Params/Capnp native 빌드 | 성공, 약 81초 |
| C4 모델 거래/주차 가드/네이티브 Params | 17 통과 |

C4 검사는 **합성 차량 신호·임시 Params·로컬 HTTP·시험 파일**로 승인→다운로드→해시→설정 저장→실행 확인 메시지 구분을 검사했다. 실제 주행 모델을 새로 학습하거나 실행한 결과는 아니다. 공개 카탈로그 68개의 selector v15 호환은 확인했다.

현재 사용 중인 C4의 D290 설치와 실제 모델은 유지한다. D293 전체 설치/부팅, 실제 차량 신호로 폰 선택·공식 모델 다운로드·다음 기동 추론 확인, 실차 주행은 별도 검증 대상이다. 자동 도로 입력과 제어는 OFF다. 기존 D290의 크루즈 미설정/늦은 경로 복구 수정은 소스에 포함한다.

## 빌드와 검사

이 브랜치는 전체 원본 태그 `c440933a65fa2c669a9926c8112ae352d3600f07`에 Koranipilot 변경을 올린 **개발 소스**다. 기존 `koranipilot-b1-home` 기기 배포 브랜치는 그대로 둔다. 자동 설치용 prebuilt가 아니다.

원본 submodule과 Git LFS 객체를 준비한 뒤 upstream C4 빌드 절차를 사용한다. 새 `common/params_keys.h`와 `cereal/custom.capnp`가 포함되므로 Python 파일만 복사해 설치하면 안 된다. upstream LFS는 원래 `.lfsconfig` 저장소를 사용한다. 이 브랜치에서 upstream Discourse/게시/배포 GitHub Actions는 제거했다.

```sh
# 빌드된 C4 소스 작업 폴더에서, 테스트 전용 임시 파일/합성 상태 사용
python -m unittest discover -s selfdrive/ui/sunnypilot/mici/korean/tests -p 'test_phone_*.py'
python -m unittest -v sunnypilot.models.tests.test_selection

# Android SDK 36 / JDK 21 / Gradle 8.14.3
cd phone/android
gradle :manager:assembleDebug :manager:lintDebug :manager:testDebugUnitTest
```

폰 소스에는 :manager 모듈과 공용 HTTPS/GPS Java 파일만 포함한다. 카카오 키·기기 인증서·개인 주행 기록·서명 개인키는 포함하지 않는다. 카카오 기능을 쓰려면 사용자의 앱 등록과 앱 내 키 입력이 필요하다. 제공 APK는 기존 관리 앱과 같은 로컬 개발 서명이며, 소스를 따로 빌드하면 서명이 달라질 수 있다.
