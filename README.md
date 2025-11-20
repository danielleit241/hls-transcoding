# Firebase Emulator - Property Video Story Testing

## Giới thiệu

Dự án này sử dụng Firebase Storage Emulator để test tính năng upload và quản lý video story cho bất động sản.

## Yêu cầu

- Backend server chạy tại: `http://localhost:5094`
- Firebase Storage Emulator chạy tại: `http://127.0.0.1:5003/`

## Hướng dẫn sử dụng

### Bước 1: Đăng nhập và lấy token xác thực

**Endpoint:** POST `/api/auth/login`

**Request Body:**

```json
{
  "keyLogin": "testuser@email.com",
  "password": "testpassword"
}
```

**Response:** Token xác thực (JWT) sẽ được trả về để sử dụng cho các request tiếp theo.

---

### Bước 2: Tạo Property (Bất động sản)

**Endpoint:** POST `/api/properties`

**Request Body:**

```json
{
  "title": "Sunshine City Apartment",
  "name": "Sunshine City Block A",
  "slug": "sunshine-city-block-a",
  "description": "Căn hộ mẫu để test",
  "transactionType": "ForSale",
  "type": "Apartment",
  "status": "Available",
  "adminNote": "Test note",
  "code": "APT-001",
  "ownerId": "USER-123",
  "location": {
    "address": "123 ABC Street",
    "city": "HCM",
    "district": "Binh Thanh",
    "ward": "Ward 22",
    "latitude": 10.7769,
    "longitude": 106.7009
  },
  "propertyDetails": {
    "bedrooms": 2,
    "bathrooms": 1,
    "livingRooms": 1,
    "kitchens": 1,
    "landArea": 80,
    "landWidth": 8,
    "landLength": 10,
    "buildingArea": 75,
    "numberOfFloors": 1,
    "hasBasement": false,
    "floorNumber": 1,
    "apartmentOrientation": "SouthEast",
    "furnished": true
  },
  "priceDetails": {
    "salePrice": 500000,
    "rentalPrice": 0,
    "pricePerSquareMeter": 6250,
    "currency": "USD",
    "depositAmount": 1000,
    "maintenanceFee": 50,
    "paymentMethods": ["BankTransfer"]
  },
  "amenities": {
    "parking": true,
    "elevator": true,
    "swimmingPool": false,
    "gym": false,
    "securitySystem": true,
    "airConditioning": true,
    "balcony": true
  },
  "images": ["https://example.com/image1.jpg"],
  "yearBuilt": 2020,
  "floorPlans": ["https://example.com/floorplan1.pdf"],
  "legalDocuments": ["Contract.pdf"],
  "isDraft": false
}
```

**Response:** Thông tin property đã được tạo, bao gồm ID để sử dụng cho bước tiếp theo.

---

### Bước 3: Upload Video lên Firebase Storage

**Directory:** `Revoland/PropertyVideos/Original`

**Cách thực hiện:**

- Sử dụng Firebase Storage Emulator để upload video
- Video sẽ được lưu trong thư mục `Revoland/PropertyVideos/Original/`
- Định dạng file name: `{uuid}_{duration}_{resolution}_{size}.mp4`
- Ví dụ: `1a2b3c4d-5678-4e9f-abcd-1234567890ed_17s_fullhd_1mb.mp4`

**Storage URL format:**

```
http://127.0.0.1:5003/storage/revoland-viewstory.firebasestorage.app/Revoland/PropertyVideos/Original/{filename}
```

---

### Bước 4: Tạo Video Story

**Endpoint:** PATCH `/api/videos/{id}`

- Phần video {id} sẽ được lấy từ response của Bước 2

**Request Body:**

```json
{
  "title": "Sample Video Story",
  "description": "A brief description of the sample video story.",
  "original_url": "http://127.0.0.1:5003/storage/revoland-viewstory.firebasestorage.app/Revoland/PropertyVideos/Original/1a2b3c4d-5678-4e9f-abcd-1234567890ed_17s_fullhd_1mb.mp4",
  "tags": ["sample", "video", "story"]
}
```

**Response:** Thông tin video story đã được tạo và liên kết với property.

---

## Khởi động Firebase Emulator

Chạy file `start-emulator.bat` để khởi động Firebase Storage Emulator:

```cmd
start-emulator.bat
```

**Response**

```
...
┌─────────────────────────────────────────────────────────────┐
│ ✔  All emulators ready! It is now safe to connect your app` │
│ i  View Emulator UI at http://127.0.0.1:5003/               │
└─────────────────────────────────────────────────────────────┘
...
```

## Lưu ý

- Đảm bảo backend server đang chạy trước khi thực hiện test
- Token xác thực cần được thêm vào header của các request sau khi đăng nhập
- Firebase Storage Emulator cần được khởi động trước khi upload video
