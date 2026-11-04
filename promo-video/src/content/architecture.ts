/**
 * What the video says about the architecture. Every middleware and tool name here is checked
 * against apps/api/src by architecture.test.ts — the video only makes true claims.
 */
export type AgentInfo = {
  tool: string
  name: string
  short: string
  source: string
  middleware: string[]
}

export const architecture = {
  supervisor: 'Investigation Supervisor',
  supervisorFramework: 'LangGraph StateGraph + LangChain create_agent',
  supervisorMiddleware: ['LLMToolSelectorMiddleware', 'ToolRetryMiddleware', 'ToolCallLimitMiddleware'],
  sharedMiddleware: ['ExternalEvidenceBoundaryMiddleware'],
  agents: [
    {
      tool: 'ask_cloudwatch',
      name: 'CloudWatch Observability Agent',
      short: 'CloudWatch',
      source: 'AWS CloudWatch MCP (awslabs)',
      middleware: ['CloudWatchReadOnlyPolicyMiddleware', 'ModelCallLimitMiddleware'],
    },
    {
      tool: 'ask_data_intelligence',
      name: 'Data Intelligence Agent',
      short: 'Data Intelligence',
      source: 'MongoDB MCP',
      middleware: ['TruncateToolOutputMiddleware', 'ToolCallLimitMiddleware'],
    },
    {
      tool: 'ask_github',
      name: 'GitHub Agent',
      short: 'GitHub',
      source: 'GitHub MCP (HTTP)',
      middleware: ['GitHubRepositoryAllowlistMiddleware', 'ToolCallLimitMiddleware'],
    },
    {
      tool: 'ask_knowledge',
      name: 'Knowledge Agent',
      short: 'Knowledge',
      source: 'Pinecone runbooks (RAG)',
      middleware: ['TruncateToolOutputMiddleware', 'ModelCallLimitMiddleware'],
    },
    {
      tool: 'ask_it_operations',
      name: 'IT Operations Agent',
      short: 'IT Operations',
      source: 'Atlassian MCP (Jira)',
      middleware: ['HumanInTheLoopMiddleware'],
    },
  ] satisfies AgentInfo[],
}

export const agentByTool = (tool: string): AgentInfo | undefined =>
  architecture.agents.find((agent) => agent.tool === tool)

export const STACK = [
  'LangGraph',
  'LangChain create_agent',
  'MCP',
  'FastAPI',
  'React',
  'PostgreSQL',
  'Docker',
]
