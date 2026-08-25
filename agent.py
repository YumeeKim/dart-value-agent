import json
from openai import OpenAI

def analyze_with_ai(api_key, model, corp, metrics, score):
    client=OpenAI(api_key=api_key)
    def clean(x):
        if hasattr(x,'to_dict'): return x.to_dict(orient='records')
        if isinstance(x,float) and (x!=x): return None
        if isinstance(x,dict): return {k:clean(v) for k,v in x.items()}
        if isinstance(x,list): return [clean(v) for v in x]
        return x
    payload={'company':corp,'metrics':clean(metrics),'score':score}
    prompt=f'''너는 한국 상장기업을 분석하는 냉정한 가치투자 리서치 AI다. 아래는 DART 공시 기반 재무데이터와 시장데이터를 계산한 V1 결과다. 숫자를 다시 계산했다고 가장하지 말고 주어진 값을 검증적으로 해석하라.\n\n{json.dumps(payload,ensure_ascii=False,default=str)}\n\n다음 순서로 한국어로 답하라.\n1. 한 줄 결론\n2. 가치평가: ROIC, WACC, ROIC-WACC, PBR, FCF Yield, 적정가치의 의미\n3. 산업/사업 숨은 신호: 성장의 질, 마진, 자본효율, 현금흐름\n4. 회계 이상징후: 매출채권/재고/이익-현금흐름 괴리 등. 단, 이상징후를 분식회계로 단정하지 말 것\n5. 매수 조건 3개: 숫자로 측정 가능한 조건\n6. 매도/회피 조건 3개: 숫자로 측정 가능한 조건\n7. 가장 중요한 추가 확인사항 5개\n8. 최종 판단: 공격적 매수/분할매수/관찰/회피 중 하나\n투자 조언이 아니라 분석 결과임을 마지막에 짧게 명시하라.'''
    r=client.responses.create(model=model,input=prompt)
    return r.output_text
