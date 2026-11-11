# Bulgarian demo project

The Plovdiv residential demo lets colleagues explore PM-ERP through one connected Bulgarian construction scenario: a КСС, programme, contractor bids, payment example, quality observations and coordination tasks.

## Create and open the demo

1. Deploy the updated PM-ERP version containing this feature to your server. Adding this feature to the repository does not update a running installation or create a project there.
2. Sign in with an administrator account and open **Projects** (**Проекти**).
3. Select **Create demo project** (**Създай демо проект**) on the Plovdiv demo card. The application creates the sample project and opens it.
4. Follow **DEMO · Project walkthrough** (**ДЕМО · Разходка из проекта**) on the project page. Later, use **Open demo project** (**Отвори демо проекта**) to return to it.

No `SEED_DEMO` setting or demo-login switch is required. Creation is an explicit administrator action. Repeating it while the demo exists returns the existing project and preserves edits; it does not reset the sample data.

## Give colleagues access

Open **Team** (**Екип**) in the demo project and add colleagues using their existing PM-ERP accounts. Choose a role suited to the access you intend to give:

| Role in Team | Intended use |
| --- | --- |
| Viewer (`viewer`) | Explore the project; use an account with the global viewer role for read-only access. |
| Estimator (`estimator`) | Practise estimating and cost-related work with editing permissions. |
| Project manager (`project_manager`) | Practise managing the project and its workflows. |

The demo does not create guest accounts, send invitations, or automatically share the project with all users. Each colleague signs in with their own account; normal account and module permissions still apply.

## Suggested walkthrough

| Step | What to explore |
| --- | --- |
| **КСС** | Follow quantities, unit prices and section totals for the fictional residential building. |
| **Contractor selection** | Compare three offers for the same façade and window scope, including their different prices and delivery periods. |
| **Schedule** | Review completed preparation, construction in progress and upcoming work. Dates are set relative to demo creation. |
| **Quality and design questions** | Review a sample defect, the corrective action and a request to coordinate openings through a slab. |
| **Budget and payments** | Trace the example invoice, VAT, partial payment and remaining balance. |
| **Risks and tasks** | Follow delivery risks, mitigation measures and the coordination tasks assigned to this scenario. |

The scenario uses EUR and Bulgarian text. Its financial checkpoints are:

| Checkpoint | Amount |
| --- | ---: |
| КСС excluding VAT | €1,801,140.00 |
| Illustrative 20% VAT | €360,228.00 |
| КСС including VAT | €2,161,368.00 |
| Sample structural-works invoice excluding VAT | €198,600.00 |
| Invoice VAT | €39,720.00 |
| Invoice including VAT | €238,320.00 |
| Recorded sample payment | €120,000.00 |
| Outstanding invoice balance | €118,320.00 |

All participants, quantities, prices, payments and records are fictional training examples. Prices are not market quotations; records are not official construction, accounting or signed acceptance documents. Do not replace the sample content with information that must be retained as real project records.

## Remove sample data

The ordinary project-delete action archives a project; it does not reset the demo. To permanently remove sample content, an administrator can use **Settings → Danger Zone → Remove sample data**.

**This purge removes all demo projects, including archived demos and any edits made inside them—not just the Bulgarian example.** It cannot be undone. Keep anything you need before using it. Normal projects and user accounts are retained.
