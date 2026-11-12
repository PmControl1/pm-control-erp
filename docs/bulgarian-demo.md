# Bulgarian demo projects

Three Bulgarian demos let colleagues explore PM-ERP through connected construction scenarios. Each contains a КСС, schedule, contractor bids, payments, quality observations, design questions, risks, tasks and downloadable sample files.

## Open the demo

1. Deploy the updated PM-ERP version containing this feature. A repository update does not update the running installation.
2. Sign in with any active PM-ERP account, including a viewer account.
3. Open the app's project selector and choose **Explore demo project** (**Разгледай демо проект**). The option is available even with an empty project list. On a phone, use the **Демо** action in the header. It is also available in the chat project selector and on the Projects page.
4. In **Choose a demo project** (**Изберете демо проект**), select the residential building, office renovation or logistics warehouse.
5. The first selection of each template creates your own sample project and opens its walkthrough. Selecting that template again reopens the same active copy and preserves your changes.

No administrator setup, manual team membership, `SEED_DEMO` setting or demo-login switch is required. Each account can have its own copy of each of the three templates, so people can explore without changing one another's examples. Ordinary account permissions still govern actions inside the demos. Opening the app or the chooser does not create projects; creation happens only when someone selects a template.

This is an authenticated in-app demonstration, not an anonymous public website. Existing project privacy remains unchanged. You may still deliberately share your own copy through the normal Team controls, but colleagues do not need this to explore their own demos.

## Choose a scenario

| Demo | Scope | КСС | Tender comparison |
| --- | --- | --- | --- |
| **Жилищна сграда „Марица“, Пловдив** | 24 apartments; 2,400 m² above ground and 600 m² basement. Structure is 70% complete in the initial snapshot. | 22 priced positions in 7 sections | Façade and windows; offers with 60, 45 and 90 day delivery periods. |
| **Обновяване на офис „Сердика“, София** | 900 m² office floor with 60 workplaces. Partition systems are 55% complete. | 21 priced positions in 7 sections | Office furniture; offers with 21, 14 and 35 day delivery periods. |
| **Логистичен склад „Тракия“, Пловдив** | 1,800 m² warehouse, 200 m² administrative area and four loading docks. Foundations are 65% complete. | 21 priced positions in 7 sections | Roof and façade panels plus industrial doors; offers with 45, 35 and 60 day delivery periods. |

## Suggested walkthrough

| Step | What to explore |
| --- | --- |
| **КСС** | Follow quantities, unit prices and section totals for the chosen project. |
| **Contractor selection** | Compare three offers for the same selected scope, including their different prices and delivery periods. |
| **Schedule** | Review completed preparation, construction in progress and upcoming work. Dates are set relative to demo creation. |
| **Quality and design questions** | Follow the scenario's issue: concrete cover and slab openings, office acoustic sealing and ceiling access, or warehouse anchors and assembly drawings. |
| **Budget and payments** | Trace the example invoice, VAT, partial payment and remaining balance. |
| **Risks and tasks** | Follow delivery risks, mitigation measures and the coordination tasks assigned to this scenario. |
| **Documents** | Download the КСС CSV, project guide and payment-review example. These are actual sample files. |

## Financial checkpoints

All projects use EUR and Bulgarian text. These values describe the initial samples; edits can change them.

| Checkpoint | Residential | Office renovation | Logistics warehouse |
| --- | ---: | ---: | ---: |
| КСС excluding VAT | €1,801,140.00 | €251,215.00 | €1,180,730.00 |
| Illustrative 20% VAT | €360,228.00 | €50,243.00 | €236,146.00 |
| КСС including VAT | €2,161,368.00 | €301,458.00 | €1,416,876.00 |
| Tender scope excluding VAT | €303,400.00 | €31,230.00 | €244,700.00 |
| Bid А excluding VAT | €297,332.00 | €30,605.40 | €239,806.00 |
| Bid Б excluding VAT | €315,536.00 | €32,479.20 | €254,488.00 |
| Bid В excluding VAT | €291,264.00 | €29,980.80 | €234,912.00 |
| Interim invoice `DEMO-0001` excluding VAT | €198,600.00 | €19,312.00 | €51,484.00 |
| Interim invoice VAT | €39,720.00 | €3,862.40 | €10,296.80 |
| Interim invoice including VAT | €238,320.00 | €23,174.40 | €61,780.80 |
| Payment against the interim invoice | €120,000.00 | €11,587.20 | €30,890.40 |
| Outstanding interim invoice balance | €118,320.00 | €11,587.20 | €30,890.40 |
| Separate, fully paid preparation invoice `DEMO-0000`, including VAT | €98,400.00 | €16,380.00 | €112,680.00 |

The interim invoice covers 40% of the second КСС section: the residential structure, office partitions or warehouse foundations. Physical progress is recorded separately from invoiced quantities. For example, the residential structure is 70% complete while 40% of its quantities have been invoiced.

All participants, quantities, prices, payments and records are fictional training examples. Prices are not market quotations; records are not official construction, accounting or signed acceptance documents. Do not replace the sample content with information that must be retained as real project records.

## API and compatibility

Authenticated clients can install or reopen a template with `POST /api/v1/projects/demo/bulgaria`:

```json
{"template_id": "office-renovation"}
```

| `template_id` | Project `metadata.demo_id` |
| --- | --- |
| `residential` | `pm-bg-plovdiv-v1` |
| `office-renovation` | `pm-bg-office-v1` |
| `logistics-warehouse` | `pm-bg-warehouse-v1` |

An omitted request body or `{}` selects `residential`, preserving compatibility with the original single-demo launcher. The residential demo keeps its original identifier, so an existing active copy is reused rather than replaced. Unsupported template identifiers are rejected.

The response contains `project_id`, `project_name`, `template_id` and `already_installed`. Ownership comes from the signed-in account. Repeated requests for the same account and template reuse its active project; another account or another template gets a separate copy. Reopening never resets edits or changes an existing copy to the latest sample definitions.

## Remove sample data

The ordinary project-delete action archives a project; it does not reset the demo. Selecting its template again creates a new active copy and leaves the archived copy intact. To permanently remove sample content, an administrator can use **Settings → Danger Zone → Remove sample data**.

**This purge removes all demo projects across accounts, including archived demos and any edits made inside them—not just the currently selected example.** It cannot be undone. Keep anything you need before using it. Normal projects and user accounts are retained.
