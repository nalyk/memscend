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

interface IMemoryNode {
    init(this: IExecuteFunctions): Promise<void>;
    loadMemoryVariables(): Promise<MemoryData>;
    saveContext(data: MemoryUpdate): Promise<void>;
    clear(): Promise<void>;
}

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

export class MemscendMemory implements IMemoryNode {
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

    private client: AxiosInstance | null = null;
    private credentials: MemscendCredentials | null = null;
    private scope = 'facts';
    private tags: string[] = [];
    private maxItems = 20;
    private includeDeleted = false;

    async init(this: IExecuteFunctions): Promise<void> {
        this.credentials = await this.getCredentials('memscendApi') as MemscendCredentials;
        if (!this.credentials) throw new Error('Memscend credentials not found');
        this.scope = this.getNodeParameter('scope', 0, 'facts') as string;
        const tagsString = this.getNodeParameter('tags', 0, '') as string;
        this.tags = tagsString ? tagsString.split(',').map((tag) => tag.trim()).filter(Boolean) : [];
        this.maxItems = this.getNodeParameter('maxItems', 0, 20) as number;
        this.includeDeleted = this.getNodeParameter('includeDeleted', 0, false) as boolean;

        const headers: Record<string, string> = {
            Authorization: `Bearer ${this.credentials.sharedSecret}`,
            'Content-Type': 'application/json',
            'X-Org-Id': this.credentials.orgId,
            'X-Agent-Id': this.credentials.agentId,
        };
        if (this.credentials.headers) {
            for (const header of this.credentials.headers) {
                if (header.name && header.value) {
                    headers[header.name] = header.value;
                }
            }
        }

        this.client = axios.create({
            baseURL: this.credentials.baseUrl.replace(/\/$/, ''),
            headers,
            timeout: 10000,
        });
    }

    async loadMemoryVariables(): Promise<MemoryData> {
        if (!this.client) throw new Error('Memscend memory not initialised');
        const params = {
            limit: this.maxItems,
            include_deleted: this.includeDeleted,
        };
        const response = await this.client.get<{ items: MemoryItem[] }>('/api/v1/mem/list', { params });
        const memories = response.data.items.filter((item) => !item.payload.deleted);
        const history = memories.map((item) => ({
            role: 'assistant',
            content: item.text,
        }));
        return { history };
    }

    async saveContext(data: MemoryUpdate): Promise<void> {
        if (!this.client) throw new Error('Memscend memory not initialised');
        if (!data.output) return;
        const userId = this.credentials?.userId ?? (data?.metadata?.userId as string | undefined) ?? 'default-user';
        const text = Array.isArray(data.output) ? data.output.join('\n') : String(data.output);
        if (!text.trim()) return;
        const payload = {
            user_id: userId,
            scope: this.scope,
            text,
            tags: this.tags,
        };
        await this.client.post('/api/v1/mem/add', payload);
    }

    async clear(): Promise<void> {
        if (!this.client) throw new Error('Memscend memory not initialised');
        const response = await this.client.get<{ items: MemoryItem[] }>('/api/v1/mem/list', {
            params: { limit: this.maxItems, include_deleted: true },
        });
        const ids = response.data.items.map((item) => item.id);
        if (!ids.length) return;
        await this.client.post('/api/v1/mem/delete/batch', { ids, hard: false });
    }

    async vectorStore() {
        return [];
    }
}
