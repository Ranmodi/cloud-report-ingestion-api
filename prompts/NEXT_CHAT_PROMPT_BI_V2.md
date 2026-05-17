# Prompt para continuar o projeto de BI Platform V2 em um novo chat

Chat, vamos continuar o projeto **Financial Report Ingestion — BI Platform V2**.

## Contexto do projeto

Estamos evoluindo um portal de ingestão de relatórios financeiros para uma nova plataforma robusta de Business Intelligence self-service, mantendo o portal legado em produção até a V2 estar totalmente validada.

A V2 deve permitir que usuários criem modelos de análise como no Power BI/Excel, com:

- abas;
- widgets;
- filtros;
- cruzamento de dados;
- fórmulas customizadas;
- drag-and-drop;
- redimensionamento;
- RBAC;
- gestão administrativa;
- rastreabilidade;
- segurança de consultas.

---

## Estado atual validado

### 1. Banco de Dados V2

Já foram criados schemas isolados no banco de dados da aplicação, sem afetar o portal legado:

- `app`
- `sec`
- `dw`
- `mart`
- `audit`

Foram criados:

- usuários;
- roles;
- RBAC;
- catálogo de relatórios;
- catálogo de datasets;
- catálogo de campos;
- dashboards;
- abas;
- widgets;
- jobs;
- logs;
- snapshots diários;
- views semânticas iniciais.

Um usuário master inicial foi criado e validado no ambiente privado.

---

### 2. API V2

A API foi criada com endpoints para:

- readiness;
- login;
- usuário atual;
- catálogo de relatórios;
- catálogo de datasets;
- campos de datasets;
- criação de dashboards;
- criação de abas;
- criação de widgets;
- consulta de datasets.

Funcionalidades validadas:

- login;
- permissões do usuário master;
- criação de dashboard;
- criação de aba;
- criação de widget;
- consulta de dados de posição atual.

---

### 3. Worker V2

Foi criado um worker incremental para atualizar o mart semântico.

O worker foi corrigido após erros de:

- múltiplos comandos em prepared statement;
- transação abortada;
- tipo indeterminado em parâmetro;
- atualização de snapshots;
- duplicidade em totalizadores por múltiplos snapshots.

Worker validado com atualização de:

- dimensão de contas;
- dimensão de assessores;
- dimensão de produtos;
- fato histórico de posições;
- view de posição atual;
- fato de rentabilidade/performance.

---

### 4. Scheduler

Foi criado um agendamento para acionar o worker durante a janela operacional.

Configuração recomendada:

- `attemptDeadline=900s`
- `maxRetryAttempts=0`

Motivo: o worker pode levar mais que o deadline padrão, e retries podem gerar sobreposição.

---

### 5. Frontend V2

O frontend inicial foi criado com:

- login;
- dashboard autenticado;
- lista de dashboards;
- abas estilo Excel;
- widgets;
- KPI principal;
- gráfico por produto;
- layout inicial.

---

## Problemas observados que devem ser tratados agora

1. Ao criar widget, o usuário ainda não consegue excluir widget pela interface.
2. Ao criar modelo/dashboard, o usuário ainda não consegue excluir modelo pela interface.
3. A plataforma ainda não possui a camada self-service completa:
   - selecionar dataset;
   - escolher dimensões;
   - escolher medidas;
   - aplicar filtros;
   - criar fórmulas customizadas;
   - alternar entre posição atual e histórico;
   - montar tabela dinâmica/drill-down;
   - cruzar conta, assessor, produto, ativo, data e cliente;
   - salvar modelos analíticos avançados.
4. O dataset atual de posições aponta para posição atual, o que é correto para PL/exposição atual, mas precisamos expor também histórico diário e histórico completo.
5. Precisamos proteger o projeto contra confusão entre dados atuais, snapshots diários e histórico bruto.
6. Atenção: não commitar secrets, tokens, chaves, logs com worker key, senha ou JWT no GitHub.

---

## Próximo objetivo técnico

Continuar pela:

```text
Etapa 4.1 — Semantic Layer + Query Builder
```

### Entregas esperadas

1. Criar views semânticas enriquecidas:
   - posições atuais;
   - posições diárias;
   - histórico completo de posições;
   - rentabilidade/performance;
   - contas;
   - assessores.

2. Expandir catálogo de datasets:
   - `positions_current`
   - `positions_daily`
   - `positions_history`
   - `profitability_history`
   - `accounts`
   - `advisors`

3. Expandir catálogo de campos:
   - dimensões;
   - medidas;
   - formatos;
   - agregações padrão;
   - flags de filtro/agrupamento/ordenação.

4. Evoluir `/datasets/query` para suportar:
   - múltiplas dimensões;
   - múltiplas medidas;
   - filtros avançados;
   - ordenação;
   - paginação;
   - limites;
   - fórmulas seguras;
   - auditoria de consulta;
   - RBAC.

5. Criar camada segura de fórmulas com whitelist:
   - `sum`
   - `avg`
   - `min`
   - `max`
   - `count`
   - `count_distinct`
   - `safe_divide`
   - `coalesce`
   - `abs`
   - `round`

6. Evoluir frontend:
   - dataset selector;
   - painel de campos;
   - drag/drop;
   - widget modal;
   - edit widget modal;
   - delete widget;
   - delete dashboard/model;
   - painel de filtros;
   - editor de fórmulas;
   - tabela/pivot;
   - seletor de gráfico;
   - alternância atual vs diário vs histórico.

---

## Regras importantes

1. Não permitir SQL bruto vindo do frontend.
2. Manter RBAC em todos os endpoints.
3. Separar posição atual de histórico.
4. Preservar dados brutos como recebidos.
5. Aplicar formatação monetária/percentual apenas no frontend/export.
6. Registrar auditoria de consultas e alterações.
7. Usar timeouts e limites de linhas.
8. Manter o portal legado funcionando até validação completa da V2.
