typedef MiraiToolHandler = String Function(ToolArguments args);

class ToolArguments {
  final Map<String, dynamic> raw;

  ToolArguments(this.raw);

  String string(String key) {
    final v = raw[key];
    if (v == null) return '';
    if (v is String) return v;
    return v.toString();
  }

  int intValue(String key, int fallback) {
    final v = raw[key];
    if (v is int) return v;
    if (v is double) return v.toInt();
    return fallback;
  }

  double doubleValue(String key, double fallback) {
    final v = raw[key];
    if (v is double) return v;
    if (v is int) return v.toDouble();
    return fallback;
  }

  bool boolValue(String key, bool fallback) {
    final v = raw[key];
    if (v is bool) return v;
    return fallback;
  }
}

class ToolParameter {
  final String name;
  final String typeName;
  final String description;
  final bool? required_;

  ToolParameter({
    required this.name,
    required this.typeName,
    required this.description,
    this.required_,
  });
}

class RegisterOptions {
  final String name;
  final String description;
  final List<ToolParameter> parameters;
  final int? timeout;
  final bool requireConfirmation;
  final bool alwaysInclude;
  final MiraiToolHandler handler;

  RegisterOptions({
    required this.name,
    required this.description,
    this.parameters = const [],
    this.timeout,
    this.requireConfirmation = false,
    this.alwaysInclude = false,
    required this.handler,
  });
}

class AgentOptions {
  final String? connectionCode;
  final String? edgeName;
  final String? envPath;

  AgentOptions({this.connectionCode, this.edgeName, this.envPath});
}
