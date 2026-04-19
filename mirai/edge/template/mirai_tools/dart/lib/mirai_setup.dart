import 'package:mirai_sdk/mirai_sdk.dart';

void initMirai() {
  final agent = MiraiAgent(
    AgentOptions(edgeName: 'My Dart App'),
  );
  agent.register(
    RegisterOptions(
      name: 'hello',
      description: 'Say hello to someone',
      parameters: [
        ToolParameter(
          name: 'name',
          typeName: 'string',
          description: 'Person to greet',
        ),
      ],
      handler: (args) {
        final n = args.string('name');
        if (n.isEmpty) return 'Hello, World!';
        return 'Hello, $n!';
      },
    ),
  );
  agent.runInBackground();
}
