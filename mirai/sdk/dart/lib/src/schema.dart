import 'types.dart';

Map<String, dynamic> buildToolSchema(RegisterOptions opts) {
  final properties = <String, dynamic>{};
  final required = <String>[];
  for (final p in opts.parameters) {
    properties[p.name] = {
      'type': p.typeName,
      'description': p.description,
    };
    final isRequired = p.required_ ?? true;
    if (isRequired) required.add(p.name);
  }

  final schema = <String, dynamic>{
    'type': 'function',
    'function': {
      'name': opts.name,
      'description': opts.description,
      'parameters': {
        'type': 'object',
        'properties': properties,
        'required': required,
      },
    },
  };
  if (opts.timeout != null) {
    schema['timeout'] = opts.timeout;
  }
  if (opts.requireConfirmation) {
    schema['require_confirmation'] = true;
  }
  return schema;
}
