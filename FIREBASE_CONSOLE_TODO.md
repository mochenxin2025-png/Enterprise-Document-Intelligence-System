# Firebase Console 配置清单

> EDIS 前端接入 Firebase Authentication 前需完成以下手动操作。

---

## 1. Firebase 项目创建

- [ ] 访问 https://console.firebase.google.com/
- [ ] 创建新项目（或使用已有项目）
- [ ] 记下 **Project ID**

---

## 2. Authentication 启用

- [ ] 左侧菜单 → **Authentication** → **Get started**
- [ ] **Sign-in method** 标签页：
  - [ ] 启用 **Email/Password**（无额外配置）
  - [ ] （可选）启用 Google / GitHub / Microsoft OAuth

---

## 3. Web App 注册

- [ ] 项目设置 → **General** → **Your apps** → **Add app** → **Web**
- [ ] 记下 **Firebase config** 对象（apiKey, authDomain, projectId 等）
- [ ] 这些值写入前端 `.env` 文件（见下方）

---

## 4. Service Account（后端用）

- [ ] 项目设置 → **Service accounts** → **Generate new private key**
- [ ] 下载 JSON 文件
- [ ] 将 JSON 内容写入环境变量 `FIREBASE_SERVICE_ACCOUNT_JSON`（单行）

**或**

- [ ] 服务部署到 GCP 时设置 `GOOGLE_APPLICATION_CREDENTIALS` 环境变量指向 JSON 文件路径
- [ ] 同时设置 `FIREBASE_PROJECT_ID=<your-project-id>`

---

## 5. 环境变量清单

### 前端 (.env)

```env
VITE_FIREBASE_API_KEY=AIzaSy...
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_STORAGE_BUCKET=your-project.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=123456789
VITE_FIREBASE_APP_ID=1:123456789:web:abc123
```

### 后端 (.env 或 Hermes env)

```env
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"...","private_key":"..."}
# 或
FIREBASE_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# EDIS 内部 JWT
EDIS_JWT_SECRET=<random-64-char-string>
EDIS_JWT_TTL=86400
```

---

## 6. OAuth Provider 配置（如启用）

| Provider | 需要配置 |
|---|---|
| Google | OAuth consent screen + Web client ID |
| GitHub | GitHub OAuth App → Client ID + Secret |
| Microsoft | Azure AD App Registration |

每个 provider 的 **Redirect URI** 格式：
```
https://<your-project>.firebaseapp.com/__/auth/handler
```

---

## 7. 安装步骤（后端）

```bash
cd D:\GitHub\self-media\edis
.venv\Scripts\activate
uv pip install firebase-admin
```

---

## 8. 验证清单

- [ ] `FIREBASE_SERVICE_ACCOUNT_JSON` 已设置
- [ ] `uv pip install firebase-admin` 已执行
- [ ] 前端 Firebase SDK 已安装并初始化
- [ ] Email/Password 登录在前端可用
- [ ] 后端 `FirebaseProvider.verify_token()` 可成功验证 ID Token
- [ ] JWT 签发流程端到端通（前端登录 → 后端验证 → 签发 JWT → 后续请求带 JWT）
