// Extract declarations from Dart files with the analyzer's syntactic parser (no resolution).
// stdin : JSON { "root": "<abs dir>", "files": [ "<abs path>", ... ] }
// stdout: JSON { "records": [ { file, name, kind, sig, doc, pin_text, line, public } ... ], "parse_errors": { file: count } }
//         (file relative to root). A file with parse errors yields no records: error recovery can move a
//         declaration into the wrong scope, and a wrong scope is worse than a named gap.
// pin_text joins the declaration's token lexemes with one space. Comments are not tokens, so a
// comment or whitespace edit never changes it.
import 'dart:convert';
import 'dart:io';

import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/token.dart';
import 'package:analyzer/dart/analysis/results.dart';
import 'package:analyzer/dart/analysis/utilities.dart';

final List<Map<String, Object>> out = [];
final Map<String, int> parseErrors = {};

String relPath( String root, String abs ) {
  final r = root.endsWith( '/' ) ? root : '$root/';
  return abs.startsWith( r ) ? abs.substring( r.length ) : abs;
}

String firstDocLine( AnnotatedNode node ) {
  final doc = node.documentationComment;
  if ( doc == null ) return '';
  for ( final tok in doc.tokens ) {
    var text = tok.lexeme;
    text = text.replaceFirst( RegExp( r'^\s*(///|/\*\*)' ), '' ).replaceFirst( RegExp( r'\*/\s*$' ), '' );
    text = text.replaceFirst( RegExp( r'^\s*\*' ), '' ).trim();
    if ( text.isNotEmpty ) return text;
  }
  return '';
}

Token startToken( AnnotatedNode node ) =>
    node.metadata.isNotEmpty ? node.metadata.first.beginToken : node.firstTokenAfterCommentAndMetadata;

String pinText( AnnotatedNode node ) {
  final parts = <String>[];
  Token? t = startToken( node );
  final end = node.endToken;
  while ( t != null ) {
    parts.add( t.lexeme );
    if ( identical( t, end ) || t.isEof ) break;
    t = t.next;
  }
  return parts.join( ' ' );
}

String sigOf( TypeParameterList? tp, FormalParameterList? params, TypeAnnotation? ret ) {
  final g = tp == null ? '' : tp.toSource();
  final p = params == null ? '' : params.toSource().replaceAll( RegExp( r'\s+' ), ' ' );
  final r = ret == null ? '' : ': ${ret.toSource()}';
  return '$g$p$r';
}

void emit( String file, CompilationUnit unit, String name, String kind, String sig, AnnotatedNode node, bool isPublic ) {
  out.add( {
    'file': file,
    'name': name,
    'kind': kind,
    'sig': sig,
    'doc': firstDocLine( node ),
    'pin_text': pinText( node ),
    'line': unit.lineInfo.getLocation( node.firstTokenAfterCommentAndMetadata.offset ).lineNumber,
    'public': isPublic,
  } );
}

// A member is public only when its owner is too: `shown` in `class _Hidden` cannot be reached from outside the library.
void members( String file, CompilationUnit unit, String owner, bool ownerPublic, NodeList<ClassMember> list ) {
  for ( final m in list ) {
    if ( m is MethodDeclaration ) {
      final n = m.name.lexeme;
      final label = m.isGetter ? 'get $n' : ( m.isSetter ? 'set $n' : n );
      emit( file, unit, '$owner.$label', 'method', sigOf( m.typeParameters, m.parameters, m.returnType ), m, ownerPublic && !n.startsWith( '_' ) );
    } else if ( m is ConstructorDeclaration ) {
      final n = m.name?.lexeme;
      emit( file, unit, n == null ? '$owner.$owner' : '$owner.$owner.$n', 'constructor',
          sigOf( null, m.parameters, null ), m, ownerPublic && ( n == null || !n.startsWith( '_' ) ) );
    }
  }
}

String extensionName( ExtensionDeclaration d ) {
  final n = d.name?.lexeme;
  if ( n != null ) return n;
  return 'extension_on_${( d.onClause?.extendedType.toSource() ?? 'unknown' ).replaceAll( RegExp( r'[^A-Za-z0-9_]' ), '_' )}';
}

void main() {
  final req = jsonDecode( stdin.readLineSync()! ) as Map<String, dynamic>;
  final root = req['root'] as String;
  for ( final abs in ( req['files'] as List ).cast<String>() ) {
    final file = relPath( root, abs );
    final ParseStringResult result;
    try {
      final text = utf8.decode( File( abs ).readAsBytesSync(), allowMalformed: true );
      result = parseString( content: text, path: abs, throwIfDiagnostics: false );
    } on Object catch ( e ) {
      stderr.writeln( '$file: skipped, $e' );
      continue;
    }
    if ( result.errors.isNotEmpty ) {
      parseErrors[file] = result.errors.length;
      continue;
    }
    final unit = result.unit;
    for ( final d in unit.declarations ) {
      if ( d is FunctionDeclaration ) {
        final n = d.name.lexeme;
        final label = d.isGetter ? 'get $n' : ( d.isSetter ? 'set $n' : n );
        emit( file, unit, label, 'function', sigOf( d.functionExpression.typeParameters, d.functionExpression.parameters, d.returnType ), d, !n.startsWith( '_' ) );
      } else if ( d is ClassDeclaration ) {
        final n = d.name.lexeme;
        emit( file, unit, n, 'class', '', d, !n.startsWith( '_' ) );
        members( file, unit, n, !n.startsWith( '_' ), d.members );
      } else if ( d is MixinDeclaration ) {
        final n = d.name.lexeme;
        emit( file, unit, n, 'mixin', '', d, !n.startsWith( '_' ) );
        members( file, unit, n, !n.startsWith( '_' ), d.members );
      } else if ( d is EnumDeclaration ) {
        final n = d.name.lexeme;
        emit( file, unit, n, 'enum', '', d, !n.startsWith( '_' ) );
        members( file, unit, n, !n.startsWith( '_' ), d.members );
      } else if ( d is ExtensionDeclaration ) {
        final n = extensionName( d );
        emit( file, unit, n, 'extension', '', d, !n.startsWith( '_' ) );
        members( file, unit, n, !n.startsWith( '_' ), d.members );
      } else if ( d is ExtensionTypeDeclaration ) {
        final n = d.name.lexeme;
        emit( file, unit, n, 'class', '', d, !n.startsWith( '_' ) );
        members( file, unit, n, !n.startsWith( '_' ), d.members );
      }
    }
  }
  stdout.write( jsonEncode( { 'records': out, 'parse_errors': parseErrors } ) );
}
