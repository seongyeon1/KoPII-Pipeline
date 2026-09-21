"""Build public tables, figures and an executable review notebook from measured JSON."""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import nbformat

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'research/results'


def published(value):
    """Publish six decimal places; retain full-precision measurements in output/."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: published(item) for key, item in value.items()}
    if isinstance(value, list):
        return [published(item) for item in value]
    return value


def pct(value):
    return f'{100 * value:.2f}%'


def organization_summary(data):
    result = {}
    def aggregate(values):
        return {'mean': statistics.mean(values), 'min': min(values), 'max': max(values)}
    for mode in ('gold', 'roberta'):
        result[mode] = {}
        for policy in ('raw', 'mask', 'pseudonym', 'team', 'division', 'center'):
            rows = [world['conditions'][mode][policy] for world in data['worlds']]
            measures = {}
            for level in ('team', 'division', 'center', 'topic_control'):
                for metric in ('mrr', 'recall_at_5', 'hit_at_5'):
                    measures[f'{level}_{metric}'] = aggregate([r['retrieval'][level][metric] for r in rows])
            for knowledge in ('identity_list_only', 'directory', 'directory_role_project'):
                for metric in ('expected_top1', 'realized_top1', 'candidate_count', 'target_in_candidates', 'abstention'):
                    measures[f'{knowledge}_{metric}'] = aggregate([r['privacy'][knowledge]['overall'][metric] for r in rows])
            for level in ('team', 'division', 'center'):
                for metric in ('accuracy', 'answered', 'source_top1'):
                    measures[f'qa_{level}_{metric}'] = aggregate([r['extractive_qa'][level][metric] for r in rows])
            for metric in ('name_surface_remaining', 'correct_team_marker', 'wrong_team_marker'):
                measures[metric] = aggregate([r['release'][metric] for r in rows])
            result[mode][policy] = measures
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--korean-results', type=Path, default=ROOT / 'output/korean-settings/results.json')
    args = parser.parse_args()
    e2 = json.loads(args.korean_results.read_text())
    e3 = json.loads((ROOT / 'output/organization-study/results.json').read_text())
    if not e2.get('complete') or not e3.get('complete'):
        raise ValueError('Refuse to publish partial experiment results')
    RESULTS.mkdir(exist_ok=True)
    for name, data in [('korean-settings', e2), ('organization-utility-risk', e3)]:
        (RESULTS / f'{name}.json').write_text(json.dumps(published(dict(data, reporting_precision_decimal_places=6)), ensure_ascii=False, indent=2) + '\n')
    summary = organization_summary(e3)
    (RESULTS / 'organization-summary.json').write_text(json.dumps(published(summary), ensure_ascii=False, indent=2) + '\n')
    extra_labels = Counter()
    for world in e3['worlds']:
        predictions = json.loads((ROOT / f"output/organization-study/predictions-{world['seed']}.json").read_text())['predictions']
        extra_labels.update(e['label'] for values in predictions.values() for e in values)
    (RESULTS / 'organization-predicted-label-counts.json').write_text(json.dumps(dict(extra_labels), indent=2) + '\n')
    for model in ('nvidia', 'fastino'):
        setting = e2['models'][model]['selection']['joint']
        config = json.loads((ROOT / f'configs/eval-{model}.json').read_text())
        config['detector'].update(threshold=setting['threshold'], boundary=setting['boundary'])
        profile = setting['profile']
        if profile != 'original':
            config['detector']['labels'] = dict(zip(e2['manifest']['protocol'][profile], config['labels'], strict=True))
        (ROOT / f'configs/eval-{model}-ko-tuned.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    tables = []
    tables.append('| 모델 / 조건 | KDPII Exact F1 (그룹 95% 구간) | 이름 재현율 | 문자 재현율 | 음성 문서 오탐 |\n|---|---:|---:|---:|---:|')
    for model, result in e2['models'].items():
        for condition, record in result['evaluations'].items():
            m = record['kdpii']; ci = m['f1_group_bootstrap_95pct']
            tables.append(f"| {model} / {condition} | {pct(m['exact']['f1'])} ({pct(ci['low'])}–{pct(ci['high'])}) | {pct(m['per_label']['PERSON_NAME']['recall'])} | {pct(m['characters']['recall'])} | {record['negative']['false_positive_documents']} / 580 |")
    e2table = '\n'.join(tables)
    e3table = '| 구간 조건 / 정책 | 팀 검색 Recall@5 | 팀 검색 MRR | 명부 공격 기대 성공률 | 명부+직급·과제 공격 기대 성공률 |\n|---|---:|---:|---:|---:|\n'
    for mode, policies in summary.items():
        for policy, values in policies.items():
            e3table += f"| {mode} / {policy} | {pct(values['team_recall_at_5']['mean'])} | {pct(values['team_mrr']['mean'])} | {pct(values['directory_expected_top1']['mean'])} | {pct(values['directory_role_project_expected_top1']['mean'])} |\n"
    (RESULTS / 'tables.md').write_text(e2table + '\n\n' + e3table)
    plt.rcParams.update({'svg.fonttype': 'none', 'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'figure.dpi': 140})
    figures = RESULTS / 'figures'; figures.mkdir(exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout='constrained')
    for ax, model in zip(axes, ('nvidia', 'fastino'), strict=True):
        result = e2['models'][model]
        labels = ['baseline', 'threshold_only', 'labels_threshold', 'boundary_threshold', 'joint']
        values = [result['evaluations'][name]['kdpii']['exact']['f1'] * 100 for name in labels]
        ax.bar(range(len(labels)), values, color=['#87909c', '#81b5c4', '#569dad', '#277e94', '#135c77'])
        ax.set_xticks(range(len(labels)), ['Initial', 'Threshold', 'Labels +\nthreshold', 'Boundary +\nthreshold', 'Joint'])
        for i, value in enumerate(values):
            ax.text(i, value + 1.3, f'{value:.1f}', ha='center')
        ref = e2['models']['roberta']['evaluations']['reference']['kdpii']['exact']['f1'] * 100
        ax.axhline(ref, color='#cf7d27', ls='--', label=f'Korean RoBERTa {ref:.1f}')
        ax.set(title=model.title(), ylabel='Exact typed-span F1 (%)', ylim=(0, 102))
        ax.legend(loc='upper left', frameon=False)
    fig.suptitle('Korean settings: validation selection, historical-test re-evaluation')
    for extension in ('png', 'svg'):
        fig.savefig(figures / f'korean-settings.{extension}', dpi=300)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout='constrained')
    colors = {'raw': '#7f8893', 'mask': '#277e94', 'pseudonym': '#63a1b7', 'team': '#c76e30', 'division': '#8a6ba0', 'center': '#58945a'}
    for ax, mode in zip(axes, ('gold', 'roberta'), strict=True):
        for policy, metrics in summary[mode].items():
            x = metrics['directory_role_project_expected_top1']; y = metrics['team_recall_at_5']
            ax.errorbar(x['mean']*100, y['mean']*100,
                        xerr=[[100*(x['mean']-x['min'])], [100*(x['max']-x['mean'])]],
                        yerr=[[100*(y['mean']-y['min'])], [100*(y['max']-y['mean'])]],
                        fmt='o', color=colors[policy], label=policy, capsize=3)
        ax.set(xlabel='Expected identity inference success (%)', ylabel='Team-query Recall@5 (%)', xlim=(-3, 105), ylim=(0, 100), title='Gold name spans' if mode == 'gold' else 'Actual RoBERTa, all predicted types')
        ax.grid(alpha=.15)
    axes[1].legend(frameon=False, loc='upper center', ncol=3)
    fig.suptitle('Synthetic worlds only · Directory + role/project attacker · Bars: three-seed min/max')
    for extension in ('png', 'svg'):
        fig.savefig(figures / f'utility-risk.{extension}', dpi=300)
    plt.close(fig)
    for svg in figures.glob('*.svg'):
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell('# 한국어 설정과 조직 범주화 실험 검토\n\n실제 실행이 완료된 집계 JSON을 읽습니다. 기존 테스트 재평가와 가상 조직 실험을 구분하며, 실제 고객 문서는 포함하지 않습니다.'),
        nbformat.v4.new_markdown_cell('## 결과 파일 확인\n두 실험이 완료되었는지 확인하고 실행 식별자를 표시합니다. 저장소 루트 또는 `research/`에서 실행하세요.'),
        nbformat.v4.new_code_cell("import json\nfrom pathlib import Path\nroot = Path.cwd()\nif not (root / 'research/results').exists():\n    root = root.parent\nresults = root / 'research/results'\ne2 = json.loads((results / 'korean-settings.json').read_text())\ne3 = json.loads((results / 'organization-utility-risk.json').read_text())\nassert e2['complete'] and e3['complete']\nprint('E2:', e2['manifest']['run_id'])\nprint('E3:', e3['manifest']['run_id'])"),
        nbformat.v4.new_markdown_cell('## 탐지 결과와 정책 비교\n표의 F1은 과거 KDPII 테스트의 재평가입니다. 공격 기대 성공률은 정답이 후보 집합에 있을 때 균등 추정하는 공격자의 성공 확률이며, 보장된 익명성이 아닙니다.'),
        nbformat.v4.new_code_cell("from IPython.display import Markdown, display\ndisplay(Markdown((results / 'tables.md').read_text()))"),
        nbformat.v4.new_markdown_cell('## 시각화\n오차 막대는 세 가상 세계의 최솟값–최댓값입니다. 모집단 신뢰구간이나 운영 검색 성능을 나타내지 않습니다.'),
        nbformat.v4.new_code_cell("from IPython.display import Image\ndisplay(Image(filename=str(results / 'figures/korean-settings.png')))\ndisplay(Image(filename=str(results / 'figures/utility-risk.png')))"),
        nbformat.v4.new_markdown_cell('## 실제 탐지의 추가 치환\n이름 외 직급·소속·업무참조 문자열도 탐지되었습니다. 실제 NER 조건의 위험 감소와 검색 손실을 이름 탐지 정확도만의 효과로 해석하면 안 됩니다.'),
        nbformat.v4.new_code_cell("print(json.loads((results / 'organization-predicted-label-counts.json').read_text()))\nfor w in e3['worlds']:\n    print(w['seed'], 'name F1:', w['detection']['exact']['f1'], 'queries:', w['query_counts'])"),
    ]
    notebook.metadata = {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}}
    nbformat.write(notebook, ROOT / 'research/01-Study-Results.ipynb')
    print('Published aggregate JSON, tables, selected configurations, figures and notebook.')


if __name__ == '__main__':
    main()
