# instant-meshes-mcp

本项目用于通过MCP协议提供3D模型处理服务，基于Instant Meshes和pymeshlab对3D模型（OBJ/GLB）进行自动重拓扑、减面和质量分析，支持批量处理、URL输入、材质贴图保留、归档管理等功能。

## 功能特色

### 🔧 模型处理功能
- **智能减面**：支持渐进式减面，避免模型破碎，保护UV坐标和贴图
- **重拓扑**：使用Instant Meshes进行网格重构，修复拓扑问题
- **自动选择**：根据模型质量自动选择最佳处理方式（减面/重拓扑）
- **格式支持**：支持GLB/OBJ输入，统一GLB输出

### 📁 文件处理能力
- **多种输入**：支持本地文件、文件夹、远程URL
- **材质保留**：自动处理MTL文件和贴图文件，保持材质完整性
- **包完整性**：验证OBJ包的完整性，检查缺失的MTL和贴图文件

### 📊 质量分析
- **网格质量检查**：分析面数、顶点数、拓扑问题
- **模型诊断**：检测破洞、分离组件、边长异常等问题
- **处理建议**：根据模型特征提供减面建议和参数推荐

### 🗂️ 归档管理
- **自动归档**：处理完成后自动创建包含模型、贴图、日志的归档文件夹
- **归档管理**：支持列出、清理、复制归档文件夹
- **结构化存储**：model/、textures/、logs/分类存储，包含详细元数据

## 环境要求
- Python 3.8+
- Windows 10/11
- 需放置`Instant Meshes.exe`于项目根目录

## 安装依赖
```bash
pip install -r requirements.txt
```

## MCP工具函数

### 1. process_model - 统一模型处理
主要的模型处理工具，支持减面和重拓扑：

```python
# 自动处理（智能选择减面或重拓扑）
result = await process_model(
    input_model="model.glb",
    target_faces=5000,
    operation="auto"  # auto/simplify/remesh
)

# 纯减面处理
result = await process_model(
    input_model="model.obj",
    target_faces=3000,
    operation="simplify",
    preserve_uv=True
)

# 重拓扑处理
result = await process_model(
    input_model="broken_model.obj",
    target_faces=8000,
    operation="remesh",
    mode="fine"  # balanced/fine/coarse/fix_holes
)
```

**参数说明：**
- `input_model`: 输入模型路径（支持GLB/OBJ文件、文件夹或URL）
- `target_faces`: 目标面数
- `operation`: 操作类型
  - `auto`: 自动选择（水密模型用simplify，有问题的用remesh）
  - `simplify`: 纯减面，保持原有网格结构
  - `remesh`: 重拓扑，修复网格问题
- `mode`: 重拓扑模式（balanced/fine/coarse/fix_holes）
- `preserve_boundaries`: 是否保持边界特征
- `preserve_uv`: 是否保持UV坐标
- `create_archive`: 是否创建归档文件夹（默认true）

### 2. analyze_model - 模型质量分析
分析模型质量和文件结构：

```python
# 自动分析
analysis = await analyze_model(
    input_path="model.obj",
    analysis_type="auto"
)

# 完整分析
analysis = await analyze_model(
    input_path="model_folder/",
    analysis_type="full"
)

# 仅质量分析
quality = await analyze_model(
    input_path="model.glb",
    analysis_type="quality"
)
```

**分析类型：**
- `auto`: 自动检测输入类型并选择合适分析
- `quality`: 网格质量分析（面数、拓扑、建议等）
- `folder`: OBJ文件夹结构分析
- `validation`: OBJ包完整性验证
- `full`: 执行所有可用分析

### 3. manage_archives - 归档管理
管理处理后的模型归档：

```python
# 列出归档
archives = await manage_archives(action="list", limit=10)

# 清理旧归档（预览模式）
cleanup = await manage_archives(
    action="clean", 
    days_to_keep=30, 
    dry_run=True
)

# 实际清理
cleanup = await manage_archives(
    action="clean", 
    days_to_keep=30, 
    dry_run=False
)

# 复制归档
copy_result = await manage_archives(
    action="copy",
    archive_name="model_20241201_143022",
    copy_to="./extracted_models/"
)

# 获取归档目录信息
info = await manage_archives(action="info")
```

## 使用方法

### 1. 启动MCP服务
```bash
python server.py
```

### 2. 通过MCP客户端调用

```json
{
  "method": "tools/call",
  "params": {
    "name": "process_model",
    "arguments": {
      "input_model": "https://example.com/model.glb",
      "target_faces": 5000,
      "operation": "auto",
      "create_archive": true
    }
  }
}
```

### 3. mcp.json配置示例

```json
{
  "mcpServers": {
    "instant-meshes-mcp": {
      "command": "python",
      "args": [
        "your_abs_dir/instant-meshes-mcp/server.py"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

## 工作流程示例

### 基础模型简化
```python
# 1. 分析模型
analysis = await analyze_model("input.glb", "auto")
print(f"原始面数: {analysis['mesh_quality']['faces']}")
print(f"推荐目标: {analysis['mesh_quality']['recommended_target_faces']}")

# 2. 处理模型
result = await process_model(
    input_model="input.glb",
    target_faces=analysis['mesh_quality']['recommended_target_faces'],
    operation="auto"
)

# 3. 管理归档
archives = await manage_archives("list")
print(f"已创建归档: {result}")
```

### 批量文件夹处理
```python
# 分析文件夹结构
folder_analysis = await analyze_model("model_folder/", "folder")

# 处理主模型
result = await process_model(
    input_model="model_folder/",
    target_faces=5000,
    operation="simplify"
)
```

## 主要依赖包
- **trimesh**: 3D模型格式转换和几何处理
- **pymeshlab**: 网格简化和修复
- **requests**: 远程文件下载
- **psutil**: 进程管理
- **mcp**: MCP协议支持

## 目录结构
```
instant-meshes-mcp/
├── server.py              # 主服务与MCP工具实现
├── Instant Meshes.exe     # 重拓扑核心程序
├── output_remesh/         # 输出模型目录
├── archives/              # 归档文件夹目录
├── temp/                  # 临时文件目录（自动清理）
├── logs/                  # 运行日志目录
├── requirements.txt       # Python依赖
└── README.md             # 项目说明
```

## 归档结构
每次处理完成后创建的归档文件夹结构：
```
archives/model_20241201_143022/
├── model/                 # 主模型文件和MTL
│   ├── model.glb
│   └── model.mtl
├── textures/              # 贴图文件
│   ├── diffuse.jpg
│   └── normal.png
├── logs/                  # 处理日志
│   └── process_model_20241201_143022.log
└── info.json             # 处理元数据和配置信息
```

## 特色功能

### 渐进式减面
- 大幅减面时自动分步进行，避免模型破碎
- 特别保护带UV坐标的模型
- 智能边界保护和拓扑保持

### 智能材质处理
- 自动检测和复制MTL文件
- 支持多种贴图类型（diffuse、normal、specular等）
- 修正文件引用路径，确保材质正确加载

### 质量监控
- 实时检测模型质量问题
- 提供处理建议和参数推荐
- 自动生成质量报告

## 注意事项
- 仅支持Windows平台（依赖Instant Meshes.exe）
- 输入支持OBJ和GLB格式
- 输出统一为GLB格式，保留材质和贴图
- 所有临时文件在处理完成后自动清理
- 日志文件按时间戳命名，便于追踪处理历史

## 错误处理
- 明确的错误信息和日志记录
- 自动清理临时文件，即使在异常情况下
- 超时保护，防止Instant Meshes进程卡死
- 模型质量验证，确保输出结果可用 