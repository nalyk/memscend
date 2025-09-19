import type { INodeTypeDescription } from 'n8n-workflow';
import { MemscendMemory } from './memory/MemscendMemory.memory';

export const nodes = [MemscendMemory];
export const nodeTypes = [{
    type: 'memory',
    name: 'memscendMemory',
    class: MemscendMemory,
    description: (MemscendMemory.prototype as unknown as { description: INodeTypeDescription }).description,
}];

export const credentials = [
    require('./credentials/MemscendApi.credentials'),
];
