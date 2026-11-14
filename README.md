# 고라니파일럿 2.0 (Koranipilot 2.0)

**써니파일럿(sunnypilot C4) 순정 뼈대** 위에 **당근웹 스타일 한글 폰 리모컨**과 **안드로이드 카카오내비 기반 방지턱 · 코너 · 단속카메라 감속**을 가볍게 얹은 콤마4(Comma 4) 전용 프로젝트입니다.

---

## 1. 무엇이 달라졌나요?

- **순정 써니파일럿 뼈대 유지**: 콤마4에서 바로 켜지고 업데이트되는 검증된 C4 빌드(`sunnypilot v2026.002.002`)를 그대로 씁니다.
- **폰으로 보는 초간단 한글 웹 리모컨 (`:7000`)**:
  - 콤마4 설정에서 **korani qr**을 누르고 폰 카메라로 QR을 찍기만 하면, 별도 앱이나 복잡한 연결 없이 폰 웹브라우저로 바로 열립니다.
  - 써니파일럿 74개 주요 설정 한글 조절, 주행 모델 변경, 방지턱·코너·카메라 미세 조정을 한 화면에서 할 수 있습니다.
- **방지턱 & 코너 우선 감속**:
  - **과속방지턱 감속**: 카카오내비에서 방지턱 좌표를 받아, 방지턱 앞에서 미리 부드럽게 목표 속도(기본 `25 km/h`)까지 줄입니다.
  - **코너(커브) 감속**: 써니의 비전 코너 감속 민감도(`corner_vision_scale`)를 조절할 수 있고, 카카오내비 급커브 구간 감속도 함께 동작합니다.
  - **과속 · 구간단속 감속**: 단속 카메라/구간단속 여유 속도(`+offset`)를 지원합니다.
  - **안전운전 모드 바로 지원**: 목적지를 찍지 않고 **[주행 연동 시작]**만 눌러도 내비 켜둔 채 방지턱 · 커브 · 카메라를 바로 감지합니다.

---

## 2. 콤마4(C4)에 설치하기

콤마4 설치 화면(Custom Software URL)에 아래 주소를 입력하세요:

```text
installer.comma.ai/JM1405
```

*(기본 브랜치 `koranipilot`이 자동으로 설치됩니다.)*

---

## 3. 폰으로 한글 설정하기 (웹 리모컨)

1. 콤마4와 스마트폰을 **같은 Wi-Fi 또는 폰 핫스팟**으로 연결하세요.
2. 콤마4 화면에서 **설정(톱니바퀴) → `korani qr`** 버튼을 누르세요.
3. 폰 기본 카메라로 화면 오른쪽 **QR 코드**를 비추고 뜨는 주소를 누르세요.
4. 맨 위 초록 버튼 **`고라니 추천 세팅 한 번에 켜기`**를 누르면 기본 세팅이 완료됩니다!

---

## 4. 안드로이드 내비 연동 앱 설치 & 사용법 (방지턱 · 커브 · 단속)

1. 안드로이드 폰에서 아래 링크로 APK를 받아 설치하세요:
   - 👉 [고라니파일럿 내비 앱(APK) 다운로드](https://github.com/JM1405/openpilot/releases/download/latest-apk/koranipilot-companion.apk)
   *(또는 3번 QR 웹 리모컨 화면 안의 `안드로이드 앱(APK) 받기` 버튼으로도 받을 수 있어요.)*
2. **최초 1회만** [카카오 디벨로퍼스](https://developers.kakao.com/)에서 내 앱을 만들고 **Android 플랫폼**에 앱 화면의 **`패키지명 복사`**, **`키 해시 복사`** 버튼을 눌러 붙여넣은 뒤, **네이티브 앱 키(32자리)**를 입력하고 저장하세요.
   *(한 번 저장하면 다음 주행부터는 다시 입력할 필요가 없어요.)*
3. 차에 타면 폰 핫스팟으로 콤마4를 연결한 뒤, 앱을 열고 **`주행 연동 시작 ▶`**만 누르세요!
   - C4와 같은 네트워크에 있으면 자동으로 연결되며, 안 되면 웹 리모컨의 **`폰 내비 앱 자동 연결`** 버튼 한 번으로 연결됩니다.

---

## 구버전(v1) 보관 안내

기존 1세대 작업 내역은 안전하게 Git 태그로 보관되어 있습니다:
- `archive/v1-koranipilot-b0`
- `archive/v1-koranipilot-b1-home`
- `archive/v1-koranipilot-dev`

---

## License

Based on [sunnypilot](https://github.com/sunnyhaibin/sunnypilot) and [openpilot by comma.ai](https://github.com/commaai/openpilot) (MIT License).
THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. Always keep your hands on the wheel and pay attention to the road.
