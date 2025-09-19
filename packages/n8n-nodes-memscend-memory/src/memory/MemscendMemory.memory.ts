import axios, { AxiosInstance } from 'axios';
import type { IExecuteFunctions } from 'n8n-workflow';

type MemoryData = {
    history: Array<{ role: string; content: string }>;
};

type MemoryUpdate = {
    input?: string | string[];
    output?: string | string[];
    metadata?: Record<string, unknown>;
};

interface MemscendCredentials {
    baseUrl: string;
    sharedSecret: string;
    orgId: string;
    agentId: string;
    userId?: string;
    headers?: Array<{ name: string; value: string }>;
}

interface MemoryItem {
    id: string;
    text: string;
    payload: {
        user_id: string;
        scope: string;
        tags: string[];
        deleted?: boolean;
    };
}

type NodeState = {
    client?: AxiosInstance;
    credentials?: MemscendCredentials;
    scope?: string;
    tags?: string[];
    maxItems?: number;
    includeDeleted?: boolean;
};

export class MemscendMemory {
    description = {
        displayName: 'Memscend Memory',
        name: 'memscendMemory',
        icon: 'file:memscend.svg',
        properties: [
            {
                displayName: 'Scope',
                name: 'scope',
                type: 'options',
                default: 'facts',
                options: [
                    { name: 'Facts', value: 'facts' },
                    { name: 'Prefs', value: 'prefs' },
                    { name: 'Persona', value: 'persona' },
                    { name: 'Constraints', value: 'constraints' },
                ],
            },
            {
                displayName: 'Tags',
                name: 'tags',
                type: 'string',
                default: '',
                description: 'Comma separated list of tags to attach on writes',
            },
            {
                displayName: 'Max Memories to Load',
                name: 'maxItems',
                type: 'number',
                typeOptions: { minValue: 1, maxValue: 200 },
                default: 20,
            },
            {
                displayName: 'Include Deleted',
                name: 'includeDeleted',
                type: 'boolean',
                default: false,
            },
        ],
        credentials: [
            {
                name: 'memscendApi',
                required: true,
            },
        ],
    };

    async init(this: IExecuteFunctions): Promise<void> {
        const state = this.getWorkflowStaticData('node') as NodeState;
        const credentials = await this.getCredentials('memscendApi') as MemscendCredentials;
        if (!credentials) throw new Error('Memscend credentials not found');
        state.credentials = credentials;
        state.scope = this.getNodeParameter('scope', 0, 'facts') as string;
        const tagsString = this.getNodeParameter('tags', 0, '') as string;
        state.tags = tagsString ? tagsString.split(',').map((tag) => tag.trim()).filter(Boolean) : [];
        state.maxItems = this.getNodeParameter('maxItems', 0, 20) as number;
        state.includeDeleted = this.getNodeParameter('includeDeleted', 0, false) as boolean;

        const headers: Record<string, string> = {
            Authorization: `Bearer ${credentials.sharedSecret}`,
            'Content-Type': 'application/json',
            'X-Org-Id': credentials.orgId,
            'X-Agent-Id': credentials.agentId,
        };
        if (credentials.headers) {
            for (const header of credentials.headers) {
                if (header.name && header.value) {
                    headers[header.name] = header.value;
                }
            }
        }

        state.client = axios.create({
            baseURL: credentials.baseUrl.replace(/\/$/, ''),
            headers,
            timeout: 10000,
        });
    }

    async loadMemoryVariables(this: IExecuteFunctions): Promise<MemoryData> {
        const state = this.getWorkflowStaticData('node') as NodeState;
        if (!state.client) throw new Error('Memscend memory not initialised');
        const params = {
            limit: state.maxItems ?? 20,
            include_deleted: state.includeDeleted ?? false,
        };
        const response = await state.client.get<{ items: MemoryItem[] }>('/api/v1/mem/list', { params });
        const memories = response.data.items.filter((item) => !item.payload.deleted);
        const history = memories.map((item) => ({
            role: 'assistant',
            content: item.text,
        }));
        return { history };
    }

    async saveContext(this: IExecuteFunctions, data: MemoryUpdate): Promise<void> {
        const state = this.getWorkflowStaticData('node') as NodeState;
        if (!state.client || !state.credentials) throw new Error('Memscend memory not initialised');
        if (!data.output) return;
        const userId = state.credentials.userId ?? (data?.metadata?.userId as string | undefined) ?? 'default-user';
        const text = Array.isArray(data.output) ? data.output.join('\n') : String(data.output);
        if (!text.trim()) return;
        const payload = {
            user_id: userId,
            scope: state.scope ?? 'facts',
            text,
            tags: state.tags ?? [],
        };
        await state.client.post('/api/v1/mem/add', payload);
    }

    async clear(this: IExecuteFunctions): Promise<void> {
        const state = this.getWorkflowStaticData('node') as NodeState;
        if (!state.client) throw new Error('Memscend memory not initialised');
        const response = await state.client.get<{ items: MemoryItem[] }>('/api/v1/mem/list', {
            params: { limit: state.maxItems ?? 20, include_deleted: true },
        });
        const ids = response.data.items.map((item) => item.id);
        if (!ids.length) return;
        await state.client.post('/api/v1/mem/delete/batch', { ids, hard: false });
    }

    async vectorStore(this: IExecuteFunctions) {
        return [];
    }
}
