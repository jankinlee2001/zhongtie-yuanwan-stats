# 线上看板部署指南（免费 · 微信可开 · 自动更新）

## 方案说明

| 项目 | 选择 |
|------|------|
| 托管 | **GitHub Pages**（免费 HTTPS 公网链接） |
| 自动更新 | **GitHub Actions** 每 2 小时拉取新数据 |
| 看板 | ECharts 静态页，手机/微信适配 |
| 费用 | **0 元** |

部署完成后你会得到一个类似这样的链接：

```text
https://你的用户名.github.io/仓库名/
```

微信里直接点开即可，可转发给队友。

---

## 一次性部署（约 10 分钟）

### 1. 注册 GitHub

打开 https://github.com 注册账号（已有则跳过）。

### 2. 创建仓库

1. 点 **New repository**
2. 仓库名建议：`zhongtie-yuanwan-stats`（或任意英文名）
3. 选 **Public**（公开，Pages 免费需要）
4. 不要勾选 README，直接创建

### 3. 上传代码

在项目文件夹 `e:\我熬篮球` 打开终端，执行：

```bash
git init
git add .
git commit -m "init: 中铁元湾数据看板"
git branch -M main
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

> 首次 push 会要求登录 GitHub（浏览器授权即可）。

### 4. 开启 GitHub Pages

1. 打开仓库 → **Settings** → **Pages**
2. **Source** 选 **Deploy from a branch**
3. **Branch** 选 `gh-pages`，目录 `/ (root)`
4. 点 **Save**

> 第一次 Actions 跑完后才会出现 `gh-pages` 分支，可先进行第 5 步。

### 5. 手动触发第一次更新

1. 仓库 → **Actions** → **更新数据看板**
2. 点 **Run workflow** → **Run workflow**
3. 等待约 1–2 分钟变绿 ✅

### 6. 获取公网链接

回到 **Settings → Pages**，会显示：

```text
Your site is live at https://xxx.github.io/xxx/
```

把这个链接发到微信群即可。

---

## 自动更新机制

- **定时**：每天 10:00–23:00（北京时间）每 2 小时自动拉取
- **周五加密集**：比赛日额外在 **20:00、20:30、21:00** 各更新一次（与常规 20:00 不冲突，并发会合并）
- **背景音乐**：浏览看板时自动播放；播放视频/个人集锦时暂停，暂停或看完后恢复
- **比赛打完**：通常 1–2 小时内会出现在看板（取决于我奥数据入库时间）
- **手动**：Actions 里随时点 Run workflow 立即更新

修改展示场次：编辑 `team_config.json`：

```json
"dashboard": {
  "last_n_games": 15,
  "year": null,
  "focus_user_id": 324467
}
```

- `last_n_games`：展示最近 N 场
- `year`：设为 `2026` 则只看今年；`null` 表示不限年份

---

## 本地预览

```bash
python publish_dashboard.py
python -m http.server 8765 --directory docs
```

浏览器打开：http://127.0.0.1:8765

---

## 常见问题

**Q：微信打不开？**  
A：必须用 **https://** 开头的 GitHub Pages 链接，不能发本地文件。

**Q：数据没更新？**  
A：去 Actions 看是否失败；也可手动 Run workflow。

**Q：想换域名？**  
A：GitHub Pages 支持绑定自定义域名（Settings → Pages → Custom domain），域名需自己购买。

**Q：想加密码？**  
A：GitHub Pages 本身不支持密码。若以后要限制访问，可换 Cloudflare Pages + Access（仍有免费档）。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `publish_dashboard.py` | 拉数据 + 生成 `docs/` |
| `build_site.py` | 仅生成静态站 |
| `docs/` | 部署产物（index.html + data.json + echarts） |
| `.github/workflows/update-dashboard.yml` | 自动更新流水线 |
