# 드론 감지 → 서보모터 작동 프로젝트

## 코딩 목표

- 아무 드론(기종 무관)이 **카메라 기준 10m 이내**로 들어오면 카메라로 감지해서 **서보모터를 작동**시킨다.
- 드론 크기는 무작위다. 10m 판정은 대략이면 되고 **±2~3m 오차는 괜찮다**.
- 카메라는 **IMX477 HQ 1대로만** 해결해야 한다. 두 번째 카메라, 거울, LiDAR, 레이더 같은 부품은 추가하지 않는다.

## 하드웨어 (실행 장치)

| 부품 | 모델 |
| --- | --- |
| 메인 보드 | Raspberry Pi 5 |
| AI 가속기 | Hailo-8 |
| 카메라 | Raspberry Pi HQ Camera (Sony IMX477) 1대 |
| 렌즈 | 6mm |
| 구동부 | 서보모터 (모델 미정) |
| 서보 드라이버 | PCA9685 (서보는 여기에 연결, Pi와는 I2C) |

## 개발 장비

| 장비 | 사양 | 역할 |
| --- | --- | --- |
| ASUS F16 (주 작업용) | NVIDIA RTX 4060 노트북 GPU 8GB, Windows(추정), VMware에 Linux VM 설치됨 | 모델 학습(Windows), HEF 변환(VMware Linux), 코드 편집과 파이 접속 |
| MacBook Pro 15-inch 2019 (보조) | 2.3GHz 8코어 Intel Core i9, Intel UHD 630, 16GB | 코드 편집과 SSH 정도만. 없어도 된다 |

- 맥북은 최신 도구 지원이 끊기는 중이라 무거운 작업에 쓰지 않는다: macOS Sequoia 15가 마지막이고, PyPI의 PyTorch는 2.2.2, onnxruntime은 1.23.2가 Intel Mac용 마지막 버전이며, Homebrew는 Intel을 Tier 3로 내렸다.

## 거리 판정 방식 (결정: 크기 등급 분류)

카메라 한 장의 영상으로는 "작은 드론이 가까이"와 "큰 드론이 멀리"가 똑같이 보인다. 그래서 드론을 크기 등급으로 분류하고, 등급별 크기로 거리를 계산한다.

### 처리 흐름

1. picamera2로 한 프레임에서 두 스트림을 받는다: main 2028×1520(최대 40fps, 전체 화각), lores 640×480 RGB(Pi 5에서는 RGB lores 가능).
2. lores에서 Hailo-8로 드론을 탐지한다.
3. bbox를 main 좌표로 옮겨(×3.169) 고해상도로 잘라낸다. main 전체를 배열로 복사하지 말고 MappedArray 안에서 잘라낸 부분만 복사한다.
4. 잘라낸 이미지로 크기 등급을 분류한다(Hailo-8, 탐지 모델과 VDevice를 ROUND_ROBIN으로 공유).
5. `거리 = 초점거리(px) × 등급 크기(m) / bbox 폭(px)`. 2028 기준 초점거리는 약 1935px이다(6mm ÷ 1.55µm ÷ 2).
6. 거리가 10m 이하면 PCA9685로 서보를 작동시킨다.

### 크기 등급 (프로펠러 끝~끝 폭)

| 등급 | 예시 | 기준 크기 | 10m일 때 bbox 폭 (2028 / 640) |
| --- | --- | --- | --- |
| A1 초소형 | 65mm whoop | 0.10m | 19px / 6px |
| A2 소형 | DJI Neo, Avata 2, 3인치 FPV | 0.18m | 35px / 11px |
| B 일반 소형 | 5인치 FPV, DJI Mini 2/3/4 | 0.34m | 66px / 21px |
| C 중형 | DJI Air 3, Mavic 3, Phantom 4 | 0.53m | 103px / 32px |
| D 대형 | Inspire 3, Matrice 30/350 | 1.10m | 213px / 67px |
| E 초대형 | Agras 농업용, FlyCart | 2.46m | 476px / 150px |

### 예상 정확도 (조사 + 검산 결과)

- 등급을 맞히면 실제 10m인 드론이 대체로 7~13m로 판정된다(90% 구간). ±3m는 대체로 맞지만 ±2m는 보장되지 않는다. D, E 등급은 경계선이다.
- 등급을 틀리면 이웃 등급끼리 크기가 1.6~2.2배 차이 나서 4.5~22m에서 작동한다.
- 분류 정확도가 80~92%면 7~20%의 경우가 7~13m 밖으로 나간다(참고: 합성 데이터로 학습한 CNN이 모양이 뚜렷한 3개 기종 분류에서 92.4%).
- 약점: 모양은 같고 크기만 다른 드론. FPV 2.5~10인치, Mini/Air/Mavic, Agras T10/T25/T40, 그리고 Air 2S처럼 등급 경계에 걸친 기종.

### 오차 줄이는 방법

- 분류가 애매하면 후보 중 작은 등급을 쓴다. 그러면 놓치는 대신 조금 일찍 작동한다.
- 여러 프레임에 걸쳐 추적하면서 등급을 투표로 정한다.
- bbox는 프로펠러 끝~끝까지 일관되게 라벨링하고, 폭과 높이 중 큰 값을 쓴다.
- 노출을 1ms 이하로 짧게 고정한다(움직임 흐림을 줄이고 프로펠러가 보이게).
- OpenCV 체커보드로 초점거리(px)를 실제로 보정한다.
- 분류는 고해상도로 잘라낸 이미지로 한다. 640 영상에서는 드론이 너무 작아서 분류가 안 된다.

### 알려진 한계

- A1/A2 등급은 640 탐지 영상에서 6~11px라 탐지 자체가 어렵다. 2028 영상을 640 타일로 나눠 탐지하면 되지만(4×3=12타일), Pi 5의 PCIe x1 대역폭과 CPU 처리 때문에 fps를 낮추거나 YOLOv8n 같은 작은 모델을 써야 한다.
- 4056×3040 전체 해상도는 10fps뿐이라 빠른 드론은 프레임 사이에 1~1.5m 움직인다. 그래서 2028×1520을 기본으로 쓴다.
- 등급별 학습 데이터가 필요하다(하늘 배경 실루엣 포함). 3D 모델로 만든 합성 데이터가 도움이 된다.

### 검토했지만 안 되거나 제외한 방법 (다시 제안하지 말 것)

- 크기 하나로 가정: 드론 크기가 약 30배 차이 나서 작동 거리가 2~57m로 퍼진다. 35cm로 가정하면 DJI Neo는 4m, Mavic 3는 16m, Matrice 350은 38m에서 작동한다.
- 사진 한 장으로 거리를 추정하는 AI(Depth Anything, Metric3D 등): 하늘 배경에 단서가 없고 드론이 너무 작다. Hailo-8 Model Zoo의 Depth Anything V2는 상대 거리만 준다.
- 초점 흐림으로 거리 측정: 6mm 렌즈에서 10m와 13m 흐림 차이가 0.5px 미만이다.
- 여러 프레임 추적만으로 거리 계산: 크기·거리·속도가 같은 비율로 바뀌면 영상이 똑같아서 원리적으로 안 된다.
- 접근 속도로 "몇 초 뒤 도착" 계산: 크기와 무관하게 구할 수 있지만 거리가 아니고, 제자리 비행이면 안 된다. 보조 조건으로만 쓸 수 있다.
- 거울 스테레오, 두 번째 카메라, LiDAR, 레이더: 크기와 무관하게 거리를 잴 수 있지만, 부품 추가 없음 조건 때문에 제외.

## 개발 작업 흐름 (2026-10 조사 + 검증)

1. **1단계, 연결 확인:** Hailo가 미리 변환해 둔 Hailo-8용 YOLOv8 HEF로 카메라 → 탐지 → 거리 → 서보 전체 흐름을 먼저 돌린다. COCO 모델이라 드론 항목이 없다(새·비행기·연으로 잡히기도 함).
   - 다운로드(로그인 불필요): `https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/<v2.18.0 또는 v2.19.0>/hailo8/yolov8s.hef`. 폴더는 꼭 `hailo8`(hailo8l 아님). v2.19.1 폴더는 없다.
2. **2단계, 드론 전용 모델:** 데이터 수집 → ASUS Windows에서 학습 → VMware Linux에서 HEF 변환 → 파이에 HEF만 교체.
   - 학습: Windows에서 직접(또는 WSL2). VMware VM은 GPU를 못 쓴다(Workstation에 GPU 패스스루 없음).
   - Windows 설치 순서: 최신 NVIDIA 드라이버 → PyTorch를 CUDA 인덱스(`--index-url https://download.pytorch.org/whl/cu130`)로 먼저 설치 → 그다음 `ultralytics`. 순서가 바뀌면 CPU용 PyTorch가 깔린다.
   - 학습 스크립트는 `if __name__ == "__main__":`로 감싼다(Windows 데이터로더). NVIDIA 제어판에서 python.exe의 "CUDA - Sysmem Fallback Policy"를 "Prefer No Sysmem Fallback"으로 설정한다.
   - 변환: `yolo export model=best.pt format=hailo name=hailo8 imgsz=640 data=...` (ultralytics 8.4.97 이상, Linux x86_64 + DFC wheel 필요). 기본값이 hailo8l이라 `name=hailo8`을 꼭 넣는다. 탐지·분류 모델 둘 다 지원한다.
   - YOLOv8/YOLO11은 export 때 conf가 HEF 안의 NMS에 고정된다. 작은 드론을 위해 conf를 낮게(약 0.1~0.15) 해서 내보내고 파이에서 거른다.
   - 보정(calibration) 이미지는 실제 IMX477로 찍은 프레임 1024장 이상을 쓴다(COCO128 금지).
   - GPU 없이 변환하면 DFC가 최적화 레벨을 0으로 낮출 수 있다. 로그에서 "Reducing optimization level"을 확인한다. Ultralytics는 레벨 2를 명시하지만 CPU에서 유지되는지는 미확인이다. 더 좋은 품질이 필요하면 Ubuntu 22.04를 별도 SSD에 설치해 GPU(CUDA 12.5.1 + cuDNN 9.10)로 변환한다.
   - DFC 권장 RAM은 16GB 이상(32GB 권장, 공식 가이드는 미확인). VM에는 12GB 정도 + 스왑을 준다.
   - 변환 후 ONNX와 HEF의 정확도를 비교한다(양자화로 크게 떨어진 사례 있음).
3. **코드 작성:** ASUS의 VS Code Remote-SSH로 파이에 접속하거나, PC에서 쓰고 git/rsync로 보낸다. 카메라 화면은 파이에서 MJPEG로 스트리밍해 브라우저로 본다.

## Hailo 도구 버전 (가장 중요)

- Hailo-8은 **DFC 3.x / HailoRT 4.x / Model Zoo v2.x** 계열이다. 5.x(DFC, HailoRT, Model Zoo master)는 Hailo-10H/15 전용이라 쓰면 안 된다. Model Zoo는 반드시 v2.x 태그로 받는다.
- HEF를 만든 DFC 버전과 파이의 HailoRT 버전이 짝이 맞아야 한다. 안 맞으면 파이에서 HEF가 열리지 않는다.

| 파이 HailoRT | DFC | Model Zoo |
| --- | --- | --- |
| 4.23.x | 3.33.1 | v2.18 |
| 4.24.x | 3.34.0 | v2.19.x |

- 순서: 파이에 hailo-all 설치 → `hailortcli fw-control identify`, `dpkg -l | grep -i hailo`로 버전 확인 → 짝이 맞는 DFC를 받는다. 라즈베리파이 OS Trixie의 hailo-all은 4.23일 가능성이 높다(미확인).
- 동작 확인 후 `apt-mark hold`로 Hailo 패키지를 고정한다(이름은 `dpkg -l`에 나온 그대로). 나중에 `apt full-upgrade`로 버전이 바뀌면 HEF가 안 맞게 된다.
- DFC wheel은 Hailo Developer Zone(무료 가입)에서 받는다. 2026-09-21 Microchip이 Hailo 인수를 마쳤으므로, 받은 wheel과 문서는 따로 보관한다.

## 라즈베리파이 설정 메모

- OS: Raspberry Pi OS 64비트 Trixie(Python 3.13). Bookworm은 쓰지 않는다. Raspberry Pi Imager에서 호스트 이름, 사용자, Wi-Fi, SSH 키를 미리 설정하면 모니터 없이 쓸 수 있다.
- Hailo 설치: `sudo apt update && sudo apt full-upgrade -y && sudo rpi-eeprom-update -a` → 재부팅 → `sudo apt install dkms` → `sudo apt install hailo-all` → 재부팅. `hailo-h10-all`(Hailo-10H용)은 설치하지 않는다(둘은 같이 설치 불가).
- PCIe Gen 3는 AI HAT+에서만 자동이다. M.2 모듈을 별도 HAT에 꽂는 형태면 `raspi-config` 또는 `dtparam=pciex1_gen=3`으로 켠다.
- Python: `python3 -m venv --system-site-packages`로 venv를 만든다. picamera2, libcamera, hailo_platform, numpy, OpenCV는 apt 버전을 쓰고 pip로 다시 설치하지 않는다(hailort는 PyPI에 없다).
- 한 번에 한 프로세스만 카메라와 Hailo를 쓸 수 있다. 데모 프로그램을 끄고 실행한다.
- PCA9685: `sudo raspi-config nonint do_i2c 0`, `sudo apt install i2c-tools python3-lgpio`, `i2cdetect -y 1`에서 0x40 확인. venv에 `adafruit-circuitpython-servokit` 설치(Pi 5에서는 python3-lgpio 필요). raspi-blinka.py 설치 스크립트는 쓰지 않는다(시스템 전체 업그레이드를 함).
- 전원: 서보는 PCA9685 V+ 단자에 별도 5~6V 전원을 연결하고 접지는 파이와 공통으로 묶는다. 파이 5V 핀으로 서보를 돌리지 않는다. PCA9685 VCC는 파이 3.3V. 파이는 공식 27W 전원을 쓴다.

## 카메라·코드 메모

- HQ 카메라 기본 케이블은 15핀-15핀이라 Pi 5에 안 맞는다. Standard-Mini(15핀-22핀) 케이블이 필요하다. AI HAT+보다 먼저 연결한다.
- IMX477 초점거리(6mm 렌즈, 픽셀 1.55µm): 4056 폭에서 약 3871px, 2028 폭에서 약 1935px, 640 폭에서 약 611px. 공식 6mm 렌즈는 3MP급이라 2028×1520 모드가 맞다.
- IMX477 주요 모드: 4056×3040 10fps, 2028×1520 40fps(2×2 비닝, 전체 화각), 2028×1080 50fps(잘림), 1332×990 120fps(잘림).
- picamera2에서 센서 모드를 고정한다: `sensor={'output_size': (2028, 1520), 'bit_depth': 12}`. 안 그러면 잘린 모드가 선택될 수 있다.
- lores는 기본으로 비율을 유지하지 않는다(main의 4:3 화면을 640×640으로 늘림). HEF 입력 크기와 lores 크기, 학습 때 전처리를 일치시킨다. bbox 폭은 x축 배율(2028/640)로 변환한다.
- picamera2의 'RGB888' 배열은 메모리상 B,G,R 순서다. RGB로 학습한 모델에는 'BGR888'을 쓰거나 맞춰서 학습한다(기기에서 빨간 물체로 확인 필요).
- main과 lores는 같은 요청에서 받는다(`capture_request()` 후 `make_array('lores')`, `make_array('main')`). 따로 받으면 다른 프레임이 되어 잘라내기가 어긋난다.
- `picamera2.devices.Hailo` 헬퍼로 HEF를 실행한다. YOLOv8 NMS는 Hailo 칩이 아니라 파이 CPU에서 돈다(HailoRT 후처리). 커스텀 HEF는 nms_postprocess를 넣어 변환해야 박스 목록이 나온다.
- 코드 구조: 카메라(FrameSource), 탐지(Detector), 크기 분류(SizeClassifier), 서보(Actuator)를 교체 가능한 인터페이스로 만들고, 거리 계산과 작동 판단 로직은 하드웨어 없이 테스트할 수 있게 둔다. PC에서는 녹화 영상 + ONNX + 가짜 서보로 시험한다. 서보는 기본값을 가짜/드라이런으로 둔다.
- 녹화 영상과 모델 파일(.onnx, .hef)은 git에 올리지 않는다.

## 미정 사항

- Hailo-8 형태 (AI HAT+ 26 TOPS 보드인지, M.2 모듈 + 별도 HAT인지)
- 라즈베리파이 5 메모리 용량
- 파이에 설치될 HailoRT 버전 (4.23 / 4.24 → DFC 버전 결정)
- ASUS 노트북 RAM 용량, Windows 버전, VMware 리눅스 배포판과 버전 (Ubuntu 22.04/24.04 x86_64여야 함)
- 서보모터 모델
- 서보 동작 내용 (지정 각도로 한 번 회전, 팬/틸트 추적 등)
- 실제로 나타날 드론 기종 범위 (범위가 좁으면 등급을 줄이거나 나눠서 정확도를 올릴 수 있음)
- 등급별 학습 데이터 확보 방법
- 초소형(A1/A2) 탐지를 위해 타일 탐지를 쓸지
