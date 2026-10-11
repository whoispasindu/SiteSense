"""Build and run notebooks/01_explore.ipynb (so it is reviewable as code and re-runnable).

python notebooks/build_explore.py
"""

from pathlib import Path

import nbformat
from nbclient import NotebookClient

HERE = Path(__file__).parent
md = nbformat.v4.new_markdown_cell
code = nbformat.v4.new_code_cell

cells = [
    md(
        "# Risk model v1: data exploration and sanity checks\n\n"
        "The training data is **synthetic**: 300 projects simulated week by week by "
        "`data_generator/simulate.py`, with real Open-Meteo rainfall. Every assumption is in "
        "`data_generator/ASSUMPTIONS.md`. This notebook checks that the simulated projects look "
        "plausible and that each feature relates to the outcomes the way the assumptions say it should, "
        "before any model is trained."
    ),
    code(
        "from pathlib import Path\n"
        "import json\n"
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n\n"
        "plt.rcParams.update({'figure.dpi': 80, 'figure.figsize': (7, 3.2), 'axes.spines.top': False, 'axes.spines.right': False})\n"
        "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
        "df = pd.read_csv(ROOT / 'data' / 'snapshots.csv')\n"
        "projects = df.groupby('project_id').first()\n"
        "projects['delay_share'] = projects.delay_days / projects.planned_duration_days * 100\n"
        "print(f'{len(df):,} weekly snapshots, {len(projects)} projects')\n"
        "projects[['planned_duration_days', 'contract_value_m', 'delay_days', 'delay_share', 'overrun_pct', 'final_score']].describe().round(1)"
    ),
    md(
        "## Outcomes\n\nDelays and overruns should be common but not universal, with a long tail of badly late jobs."
    ),
    code(
        "fig, axes = plt.subplots(1, 3, figsize=(10, 3))\n"
        "axes[0].hist(projects.delay_share, bins=30, color='#3b6e8f'); axes[0].set_title('Delay, % of planned duration')\n"
        "axes[1].hist(projects.overrun_pct, bins=30, color='#b07a2a'); axes[1].set_title('Cost overrun, %')\n"
        "bands = pd.cut(projects.final_score, [-1, 39, 69, 100], labels=['Low', 'Medium', 'High']).value_counts().reindex(['Low', 'Medium', 'High'])\n"
        "axes[2].bar(bands.index, bands.values, color=['#3d8a5a', '#c9962b', '#b8473a']); axes[2].set_title('Final risk band (BR-10)')\n"
        "plt.tight_layout()\n"
        "bands / len(projects)"
    ),
    md(
        "## Sanity checks\n\n"
        "1. **The hidden management quality drives outcomes**, and its symptoms (missed reports, late "
        "deliveries, crew shortfalls) are visible in the features. The model never sees `quality` itself."
    ),
    code(
        "mid = df[(df.elapsed_pct > 40) & (df.elapsed_pct < 60)].groupby('project_id').mean(numeric_only=True)\n"
        "checks = mid[['quality', 'missing_reports_14', 'late_deliveries_count', 'avg_lateness_days', 'crew_vs_plan_pct', 'progress_gap_pct', 'budget_variance_pct']].corr()['quality'].round(2)\n"
        "print('Correlation with hidden quality at mid-project:'); print(checks.drop('quality'))\n"
        "assert checks['missing_reports_14'] < 0 and checks['progress_gap_pct'] > 0"
    ),
    md(
        "2. **Wetter towns lose more time.** Programmes allow for only half of a town's usual rain "
        "(`RAIN_ALLOWANCE`, an assumption: see ASSUMPTIONS.md), and the pace is calibrated so the median "
        "project is 10% late, so wet-zone towns should come out later than the dry zone."
    ),
    code(
        "by_town = projects.groupby('town').agg(projects=('delay_share', 'size'), median_delay_share=('delay_share', 'median')).round(1)\n"
        "by_town.sort_values('median_delay_share')"
    ),
    md(
        "3. **Falling behind early predicts finishing late.** The progress gap at mid-project against the final delay:"
    ),
    code(
        "joined = mid.join(projects[['delay_share']], rsuffix='_final')\n"
        "plt.scatter(joined.progress_gap_pct, joined.delay_share, s=10, alpha=0.6, color='#3b6e8f')\n"
        "plt.xlabel('Progress gap at mid-project (points)'); plt.ylabel('Final delay (% of plan)')\n"
        "print('correlation', round(joined.progress_gap_pct.corr(joined.delay_share), 2))"
    ),
    md(
        "4. **Features against outcomes at mid-project** (Pearson correlation). Signs should match the assumptions: behind plan, late deliveries, missed reports and short crews mean more delay; cost running over its budgeted value means more overrun."
    ),
    code(
        "features = ['progress_gap_pct', 'progress_rate_trend', 'late_deliveries_count', 'avg_lateness_days', 'rain_days_next_14', 'wet_days_ahead', 'budget_variance_pct', 'crew_vs_plan_pct', 'missing_reports_14']\n"
        "targets = mid[features].join(projects[['delay_days', 'overrun_pct']])\n"
        "targets.corr().loc[features, ['delay_days', 'overrun_pct']].round(2)"
    ),
    md(
        "## Leakage\n\n"
        "Weeks of the same project are strongly related, so a random row split would put weeks of one "
        "project in both training and test data and flatter the model. `train.py` splits **by project** "
        "(80/20) and tunes with cross-validation grouped by project."
    ),
    md("## Evaluation (from `train.py`, held-out projects)"),
    code(
        "metrics = json.loads((ROOT / 'models' / 'risk-v1.2.0' / 'metrics.json').read_text())\n"
        "rows = []\n"
        "for target, m in metrics['targets'].items():\n"
        "    rows.append({'target': target, 'model': 'LightGBM', **m['test']})\n"
        "    rows.append({'target': target, 'model': 'linear baseline', **m['baseline_test']})\n"
        "pd.DataFrame(rows).set_index(['target', 'model'])"
    ),
    code(
        "rc = metrics['risk_class']\n"
        "print(f\"F1 for the High class: {rc['f1_high']} (baseline {rc['f1_high_baseline']}); macro F1 {rc['f1_macro']}\")\n"
        "cm = pd.DataFrame(rc['confusion_matrix']['rows_true_cols_predicted'], index=['true low', 'true medium', 'true high'], columns=['pred low', 'pred medium', 'pred high'])\n"
        "cm"
    ),
    code(
        "bt = metrics['backtest']\n"
        "print(f\"Backtest: {bt['flagged']} of {bt['high_projects']} projects that ended High were flagged High,\")\n"
        "print(f\"at a median of {bt['median_flagged_at_elapsed_pct']}% of the planned duration ({bt['median_weeks_before_planned_end']} weeks before the planned end).\")\n"
        "print(f\"{bt['low_projects_ever_flagged_high']} of {bt['low_projects']} projects that ended Low were ever flagged High.\")\n"
        "pd.Series(metrics['delay_mae_by_elapsed'], name='delay MAE (days) by stage')"
    ),
    code(
        "gain = pd.Series(metrics['targets']['delay_days']['importance_gain_pct']).head(10)[::-1]\n"
        "gain.plot.barh(color='#3b6e8f', title='Delay model: share of gain by feature (%)'); plt.tight_layout()"
    ),
    md(
        "## Conclusions\n\n"
        "- The simulated projects behave as the assumptions intend; no feature has a backwards relationship.\n"
        "- The delay model clearly beats the linear baseline, and the season still ahead "
        "(`wet_days_ahead`) is among its main inputs. The overrun model is weak, and in this run the "
        "linear baseline is slightly better: most overrun comes from overheads and variations the app "
        "does not record yet.\n"
        "- These are results on simulated data. They show the pipeline works; they do not prove the model "
        "is right about real projects. Validating the assumptions with a contractor comes first."
    ),
]

notebook = nbformat.v4.new_notebook(
    cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}}
)
NotebookClient(
    notebook, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}
).execute()
nbformat.write(notebook, HERE / "01_explore.ipynb")
print("Wrote", HERE / "01_explore.ipynb")
