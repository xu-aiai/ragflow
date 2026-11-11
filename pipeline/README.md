# XC975-EV 数据抽取管线（第一批）

三份手册 → 车机数据包：**A 文档树 / B1 故障码 / C 保养周期规则**，全部确定性抽取。
规格见 `docs/project/随车助手-数据抽取规格说明.md`（§3.A、§3.B1、§3.C、§6）。

## 运行

```bash
# 在 10.90.20.110（Linux、无 DRM、装有 LibreOffice）上：
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]

python pipeline.py --input 手册A.docx --doc A --variant 国内干桥 --version 202608 --out dist/
# → dist/A_202608/：tree_A.json + fault_codes.json + maintenance_rules.json
#                   + img/ + manifest.json + audit.json
```

B 手册（.doc）由阶段 0 自动转为 .docx：优先 LibreOffice，Windows 本机无 LibreOffice 时回退 Word COM。
本机装有亿赛通 DRM：任何"Word 另存为"产物都是密文，转换产物按文件头校验，密文拒收（阶段 0）。

## 阶段

| # | 模块 | 内容 |
|---|---|---|
| 0 | `validate.py` | 文件头校验（PK / D0 CF 11 E0 / E-SafeNet 拒收） |
| 1 | `docmodel.py` | docx → 保序元素流；表格网格展开 vMerge/gridSpan |
| 2 | `numbering.py` | A/C 位置推导编号 + 目录交叉验证；B 字面编号归一 |
| 3 | `tables.py` | 表格分类：警告框/故障码表/周期表/排版表 |
| 4 | `images.py` | 图片提取转码（EMF/WMF→PNG、800px 缩放） |
| 5 | `products/` | tree（六种块规整）/ fault_codes / maintenance |
| 6 | `package.py` | manifest + sha256 |
| 7 | `audit.py` | 审核清单（规格 §3.E） |

## 测试

```bash
python -m pytest tests -q     # 自构造样例 docx，无需真实手册
```

黄金断言（A：159 节点 / 205 故障码 / 0 冲突 / 0 孤儿图 / 0 未知块）在服务器上对真实手册跑。
真实手册是保密文件，**不进 git**。

## 待校准项（对着真实手册跑第一轮时确认）

- B 字面编号归一映射（00 / 一、 / 1.2.4.1 / §1.1）的实际覆盖；
- 故障码控制器 code_id 前缀（目前只定了 行走电控=WL，其余四个待确认）；
- 同码多等级行的折叠策略（当前取最高等级）；
- 周期表项目列位置与累积/首保短语的变体；
- 变体组装脚本（A/B 故障码双来源合并、按变体清单选拷）——待"手册 Tab 是否含 B"定案。
