# 고라니파일럿 Android 관리 앱 v0.21

기기 → 주행 모델에서 현재 실행 모델, 다음 기동 모델, 다운로드/실패 상태를 확인한다. 차량 ON·P단·정차·보조 비활성에서만 C4 승인 후 모델을 선택한다. 집 수신 모드는 읽기 전용이다. 새 기능은 D293 서버가 필요하고 이전 설치본에는 업데이트 필요를 표시한다.

패키지 `dev.koranipilot.manager`, versionCode 21, Android 8+ ARM64. 같은 네트워크의 핀 고정 HTTPS와 C4 승인으로 연결한다. 관리 기능에는 카카오 키가 필요 없다. 지도/수신 기능의 개인 네이티브 앱 키는 앱 안에서 입력한다.

SDK 36, JDK 21, Gradle 8.14.3을 준비하고 `phone/android`에서 실행한다.

```sh
gradle :manager:assembleDebug :manager:lintDebug :manager:testDebugUnitTest
```

공개 소스에는 :manager와 필요한 공용 Java 파일만 포함한다. 개인 SDK 키, 기기 인증서, 주행 로그, 서명 키는 포함하지 않는다. 기존 APK와 직접 빌드한 APK의 서명은 다를 수 있다.

빌드/JVM 66개와 합성 응답의 Android 모델 UI 검사를 통과했다. 새 APK의 실제 폰↔차량 모델 변경·다음 기동 실행 확인은 남아 있다.
