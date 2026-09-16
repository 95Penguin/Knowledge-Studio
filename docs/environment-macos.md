# macOS 开发环境

## 最小环境

- Git
- JDK 17
- Maven 3.9+
- uv（负责安装和锁定 Python 3.12、创建虚拟环境、同步依赖）
- Docker Desktop（后续运行 PostgreSQL、Qdrant 和 Elasticsearch）
- Node.js 22 LTS（到 Web 阶段再装也可以）

当前机器已经检测到：JDK 17、Maven 3.9.16、uv 0.11.21、Docker/Compose、Git、Node.js 和 npm。项目已在 `ai-service/.python-version` 锁定 Python 3.12，不使用系统 Python 3.14。现阶段没有必装环境缺口。

## 1. 检查 Homebrew

```bash
brew --version
```

如果提示找不到命令，到 https://brew.sh/ 按官方方式安装。Homebrew 安装完成后，严格执行终端打印的 `shellenv` 配置提示，再重开终端。

## 2. Maven（已安装）

```bash
brew install maven
mvn -version
```

`mvn -version` 应同时显示 Maven 版本和 Java 17。使用 Homebrew 安装时通常不需要手工设置 `MAVEN_HOME`。

如果 Maven 使用了错误 JDK，检查：

```bash
/usr/libexec/java_home -V
java -version
mvn -version
```

必要时只为当前终端选择 JDK 17：

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
```

确认后再把同一行加入 `~/.zshrc`。不要复制不适合本机架构的固定 Java 路径。

## 3. 使用 uv 管理 Python 3.12 和依赖

```bash
cd ai-service
uv python install 3.12
uv sync --extra dev
uv run python --version
uv run pytest
```

`uv sync` 会根据 `pyproject.toml` 和 `uv.lock` 创建/同步项目的 `.venv`。以后不需要手动激活虚拟环境，统一使用：

```bash
cd ai-service
uv run pytest
uv run uvicorn app.main:app --reload --port 8001
```

增加或删除依赖时使用 `uv add 包名`、`uv remove 包名`；开发依赖使用 `uv add --dev 包名`。不要再运行 `pip install` 或维护 `requirements.txt`，避免环境和锁文件不一致。

## 4. Docker Desktop（已安装）

从 https://docs.docker.com/desktop/setup/install/mac-install/ 下载与芯片匹配的版本：

- Apple Silicon：Apple chip
- Intel Mac：Intel chip

安装并启动 Docker Desktop 后验证：

```bash
docker version
docker compose version
```

首期不必立刻启动所有容器。进入数据库/向量库阶段后再运行：

```bash
cd deploy
docker compose up -d
docker compose ps
```

## 5. 验证后端

```bash
cd backend
mvn test
mvn spring-boot:run
```

浏览器访问 `http://localhost:8080/api/health`。

## 6. 验证 AI 服务

```bash
cd ai-service
uv sync --extra dev
uv run pytest
uv run uvicorn app.main:app --reload --port 8001
```

浏览器访问 `http://localhost:8001/health`。

## 7. 暂时不用安装

- 本地大模型和 CUDA（Mac 没有 NVIDIA CUDA 环境）
- Kubernetes
- Redis、Kafka、RabbitMQ
- 全局安装 Elasticsearch、PostgreSQL 或 Qdrant
- 前端框架和 npm 包（Node.js/npm 已有，可推迟到 P0-5 初始化）
