import type { ICredentialType, INodeProperties } from 'n8n-workflow';

export class MemscendApi implements ICredentialType {
    name = 'memscendApi';
    displayName = 'Memscend API';
    properties: INodeProperties[] = [
        {
            displayName: 'Base URL',
            name: 'baseUrl',
            type: 'string',
            default: 'http://localhost:8080',
            placeholder: 'http://127.0.0.1:8080',
            description: 'Memscend HTTP gateway base URL (no trailing slash)',
            required: true,
        },
        {
            displayName: 'Shared Secret',
            name: 'sharedSecret',
            type: 'string',
            typeOptions: { password: true },
            default: '',
            required: true,
        },
        {
            displayName: 'Organisation ID',
            name: 'orgId',
            type: 'string',
            default: '',
            required: true,
        },
        {
            displayName: 'Agent ID',
            name: 'agentId',
            type: 'string',
            default: '',
            required: true,
        },
        {
            displayName: 'Default User ID',
            name: 'userId',
            type: 'string',
            default: '',
            description: 'Optional default user identifier for writes',
        },
        {
            displayName: 'Additional Headers',
            name: 'headers',
            type: 'fixedCollection',
            typeOptions: {
                multipleValues: true,
            },
            default: {},
            options: [
                {
                    name: 'header',
                    displayName: 'Header',
                    values: [
                        {
                            displayName: 'Name',
                            name: 'name',
                            type: 'string',
                            default: '',
                        },
                        {
                            displayName: 'Value',
                            name: 'value',
                            type: 'string',
                            default: '',
                        },
                    ],
                },
            ],
        },
    ];
}
