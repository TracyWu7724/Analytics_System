# Lightdash context layer — 学习笔记

读的源码(`lightdash/lightdash` main 分支,sparse clone):

| 主题 | 文件 |
|---|---|
| 数据模型(Explore / Join / Table) | `packages/common/src/types/explore.ts` |
| 字段模型(Dimension / Metric) | `packages/common/src/types/field.ts` |
| YAML 里能写什么 | `packages/common/src/types/dbt.ts` |
| 编译器(引用解析、校验) | `packages/common/src/compiler/exploreCompiler.ts` |
| join 放大检测 | `packages/common/src/compiler/joinInflation.ts` |
| Agent 怎么用它 | `packages/backend/src/ee/services/ai/tools/runMetricQuery.ts`、`grepFields.ts` |

> 说明:`runMetricQuery.ts`、`exploreCompiler.ts` 的核心函数我读了正文;`grepFields`、`joinInflation` 只读了开头、类型和签名,下面对它们的描述有一部分是推断,标了"(推断)"。

## 1. 核心心智模型

```
YAML (人写)  ──compile──▶  Explore (编译产物)  ──▶  Agent 的工具只能选里面的字段
                              │
   校验在这里发生:引用是否存在、是否自引用、聚合规则、join 是否合法
```

关键点:**context layer 不是塞进 prompt 的文字,而是一个会被编译和校验的数据结构。** agent 能做什么,由编译产物决定。

## 2. 它的实体

- **Explore**:一次查询的起点。有 `baseTable` 和 `joinedTables`。
- **Table**:带 `dimensions`、`metrics`、`primaryKey`、`sets`。
- **Dimension**:`type`(string / number / timestamp / date / boolean)、`sql`、`hidden`、`groups`、`timeInterval`(时间粒度是编译出的派生维度)。
- **Metric**:`type` 是枚举(`sum`、`average`、`count`、`count_distinct`、`sum_distinct`、`min`、`max`、`median`、`percentile`、`number`…)、`sql`、`filters`、`format`、`default_time_dimension`、`drivers`。
- **Join**:`sql_on`、`type`(inner/left…)、`relationship`(one-to-many 等)、`always`(是否总是 join)、`fields`(只暴露哪些字段)。

## 3. 值得学的 8 个设计点

1. **指标有"类型",不只是一段 SQL。** `type: sum` 告诉编译器怎么聚合,编译器才能处理 join 放大等问题。你现在的 `expression: "SUM(net_sales)"` 是裸字符串,系统不知道它是求和。
2. **引用语法 `${TABLE}.col`、`${dimension}`、`${table.metric}`。** 字段互相引用,不重复写列名。改一处,所有引用跟着变。
3. **编译期校验,错误分类明确。** 自引用、引用不存在的表或字段都会抛 `CompileError`。类型里还有 `InlineErrorType`(`MISSING_TABLE`、`FIELD_ERROR`、`WAREHOUSE_COLUMN_ERROR`、`DUPLICATE_FIELD_NAME`…)。一个字段坏了,整个 explore 可以带 `warnings` 继续用。
4. **聚合规则被强制。** 聚合型 metric 只能引用 dimension;非聚合型 metric(`type: number`)引用其它 metric,除非 SQL 自带聚合函数。这避免了"指标套指标"写出错误 SQL。
5. **join 放大是一等问题(推断)。** `joinInflation.ts` 的输入是每张表的 `primaryKey`、join 的 `relationship` 和实际 join 的表,用来找出"被 join 放大的指标"。这就是为什么 `Metric` 有 `sum_distinct` 和 `distinctKeys`。
6. **给 AI 的专用字段:`ai_hint`。** 模型、维度、指标、分组都能写,支持字符串或列表。和给人看的 `description` 分开。没有"同义词"这个一等字段,字段发现靠 `grepFields`(字面匹配,没结果时回退到全文检索,并优先排已验证、有治理的字段;推断)。
7. **权限在字段上。** 维度和指标可写 `required_attributes` / `any_attributes`(用户属性),模型可写 `sql_filter`、`required_filters`。权限是语义层的一部分,不是 agent 外面再包一层。
8. **BI as code。** 语义层是 Git 里的 YAML,靠 `lightdash validate` 和 preview 在 CI 里检查。

## 4. Agent 怎么用它(最重要的一段)

`runMetricQuery.ts` 里 agent 的工具**不接受 SQL**。输入是:explore 名、维度列表、指标列表、过滤、排序。执行前会依次校验:

1. 选的字段是否真实存在(`validateSelectedFieldsExistence`)
2. 维度位置放的是维度、指标位置放的是指标(`validateFieldEntityType`)
3. 过滤条件放对位置:指标过滤和维度过滤不混(`validateMetricDimensionFilterPlacement`)
4. 排序字段必须已被选中(`validateSortFieldsAreSelected`)

然后由代码把查询编译成 SQL 并执行。执行时还并行做两件事:一个 LLM 审查器(`createQueryReviewer`)判断这个查询是否回答了问题;**结果为空时**调用 `diagnoseEmptyResult`,给出重试建议,而不是直接说"没数据"。

对比你的做法:LLM 写 SQL,然后用 guard 检查。Lightdash 是 LLM 选字段,代码生成 SQL。错误的 SQL 在它那里**不可能被生成**,在你这里只能被事后拦截。

## 5. 和你的 `backend/mdl/schema.yaml` 对照

| 能力 | Lightdash | 你的 MDL |
|---|---|---|
| 指标类型 | 枚举 | 裸 SQL 字符串 |
| 维度 | 一等公民,有类型和时间粒度 | 只有 `column_descriptions` 里的文字描述 |
| 字段引用 | `${...}` | 无 |
| join | `relationship`、类型、`always`;检测放大 | 两条重复的 join,无关系类型 |
| 校验 | 编译期 + warehouse 列校验 | 加载时无校验;**表和列可能与真实库不一致** |
| AI 提示 | `ai_hint` + `description` | `synonyms`(用关键字匹配注入 prompt) |
| 权限 | 字段级属性 | 表级 denylist(在 agent 外) |
| 产出 | 编译后的结构,工具只能选字段 | 一段文字,拼进 prompt |

你的 MDL 里有的、Lightdash 里没有一等支持的:`value_constraints`(枚举值约束)。这对你反而是优点,可以保留。

## 6. 设计你自己的 context layer 时的检查清单

- [ ] 指标有类型(sum / avg / ratio…),并能编译成 SQL
- [ ] 维度单独定义,时间维度带粒度(day / month / quarter)
- [ ] 字段能互相引用,不重复写列名
- [ ] 启动时校验:每个表、列在数据库里真实存在;引用不悬空;无重名
- [ ] join 带 `relationship` 和主键,能提示放大风险
- [ ] 每个字段有 `description` 和 `ai_hint`
- [ ] agent 的主工具选字段,不写 SQL;`run_sql` 只做兜底
- [ ] 工具入参校验(字段存在、类型对位、过滤放对位置)
- [ ] 空结果有诊断,不直接回答"没有数据"
- [ ] 权限能挂到字段上
- [ ] 改动能被 CI 校验(用评估集回归)
