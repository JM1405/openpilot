# Koranipilot · 고라니파일럿

**D293 개발 소스 · 실차 검증 완료 릴리스가 아님.** sunnypilot 기반 comma four / Android 개인용 개발 프로젝트.

폰 앱 **기기 → 주행 모델**에서 호환 모델을 선택한다. 차량 ON, P단, 정차, 주행 보조 비활성 조건을 요청·다운로드·저장 때 확인한다. 실패나 취소 시 기존 모델을 유지하며, 다운로드 완료와 다음 기동 후 실제 실행 확인을 구분한다. 기본 CD210 복귀도 지원한다.

[모델 교체·검증·빌드](docs/koranipilot/model-selection-d293.md) · [Android 앱](phone/android/README.md)

D290의 크루즈 미설정 MPC 및 늦은 경로 복구 수정도 포함한다. 도로 입력/자동 감속은 기본 OFF다. 합성 검증과 집 기동은 차량·도로 성능 입증이 아니다. 현재 장치 D290은 이번 게시로 자동 변경되지 않는다.

`koranipilot-dev`는 원본 전체 소스와 변경을 보관하는 브랜치다. 기존 `koranipilot-b1-home` 배포 브랜치는 유지한다. 모델 가중치를 새로 학습한 릴리스가 아니며 upstream 호환 모델 카탈로그를 사용한다.

원본 프로젝트·라이선스: [sunnypilot](https://github.com/sunnypilot/sunnypilot), [LICENSE.md](LICENSE.md).
